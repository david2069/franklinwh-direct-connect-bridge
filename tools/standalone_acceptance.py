#!/usr/bin/env python3
"""Release gate for the two standalone installs (owner, 2026-11-05): the published container
image and a fresh pip install of the release, each as a new user gets it.

    standalone_acceptance.py container --version 0.5.31 --out results/
    standalone_acceptance.py pip --ref main --version 0.5.31 --out results/

container: pulls ghcr.io/david2069/<arch>-franklinwh-direct-connect-bridge:<version> and runs it
the way docker-compose.yml does (``docker`` or ``podman``, whichever is installed), with a
fresh data directory. pip: a fresh venv, ``pip install "<repo>@<ref>[cloud]"``, then
``franklinwh-direct-connect-bridge run`` in a fresh directory. CI's install-smoke covers the
``docker compose`` file itself, on every pull request.

Each run is a new install, so Security is on (#457). The checks are tools/install_smoke.py's
(8101 redirects to HTTPS, the bridge's own certificate, sign-in, a mock gateway that polls,
no ERROR in the log), then a browser pass when Playwright is available: 8101 lands on the
sign-in page, the first admin signs in, the dashboard loads with no console errors and no
failed calls. Each run's evidence goes to <out>/<UTC stamp>_<install>_<version>/.
Mock gateway only; it never touches an aGate.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import platform
import secrets
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import install_smoke  # noqa: E402

REPO = "https://github.com/david2069/franklinwh-direct-connect-bridge"
IMAGE = "ghcr.io/david2069/{arch}-franklinwh-direct-connect-bridge:{version}"
HTTP_PORT, HTTPS_PORT = 18201, 8102     # HTTPS keeps its own number: 8101 redirects to :8102
NAME = "fwh-dc-standalone-acceptance"


def engine() -> str:
    for e in ("docker", "podman"):
        if shutil.which(e):
            return e
    raise SystemExit("neither docker nor podman is installed")


def start_container(version: str, data: pathlib.Path, env: dict) -> tuple[list[str], str]:
    eng = engine()
    arch = "aarch64" if platform.machine() in ("arm64", "aarch64") else "amd64"
    image = IMAGE.format(arch=arch, version=version)
    subprocess.run([eng, "rm", "-f", NAME], capture_output=True)
    subprocess.run([eng, "pull", image], check=True)
    cmd = [eng, "run", "-d", "--name", NAME, "-p", f"{HTTP_PORT}:8101", "-p", f"{HTTPS_PORT}:8102",
           "-v", f"{data}:/data"]
    for k, v in env.items():
        cmd += ["-e", f"{k}={v}"]
    subprocess.run(cmd + [image], check=True)
    return [eng, "logs", NAME], image


def start_pip(ref: str, work: pathlib.Path, env: dict, log: pathlib.Path) -> subprocess.Popen:
    py = shutil.which("python3.12") or shutil.which("python3.11") or sys.executable
    subprocess.run([py, "-m", "venv", str(work / ".venv")], check=True)
    pip = work / ".venv/bin/pip"
    subprocess.run([str(pip), "install", "--quiet",
                    f"franklinwh-direct-connect-bridge[cloud] @ git+{REPO}@{ref}"], check=True)
    full = {"PATH": f"{work / '.venv/bin'}:/usr/bin:/bin", "HOME": str(work), **env,
            "HTTP_PORT": str(HTTP_PORT), "HTTPS_PORT": str(HTTPS_PORT)}
    return subprocess.Popen([str(work / ".venv/bin/franklinwh-direct-connect-bridge"), "run"],
                            cwd=work, env=full, stdout=log.open("w"), stderr=subprocess.STDOUT)


def browser(run: pathlib.Path, user: str, pw: str, check) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        check("browser pass", False, "Playwright is not installed in this Python")
        return
    console, failed = [], []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        for name, w, h, mobile in (("desktop", 1440, 900, False), ("iphone", 390, 844, True)):
            ctx = b.new_context(viewport={"width": w, "height": h}, is_mobile=mobile,
                                has_touch=mobile, ignore_https_errors=True)
            pg = ctx.new_page()
            pg.on("console", lambda m: console.append(f"[{name}] {m.text}") if m.type == "error" else None)
            pg.on("pageerror", lambda e: console.append(f"[{name}] {e}"))
            pg.on("response", lambda r: failed.append(f"{r.status} {r.url}")
                  if r.status >= 400 and not r.url.endswith("/api/gateways/0") else None)
            pg.goto(f"http://127.0.0.1:{HTTP_PORT}/")
            pg.wait_for_selector("[data-testid=signin-form]", timeout=20000)
            pg.screenshot(path=str(run / f"{name}-signin.png"))
            check(f"{name}: 8101 lands on the HTTPS sign-in page",
                  pg.url.startswith(f"https://127.0.0.1:{HTTPS_PORT}/signin"), pg.url)
            pg.fill("#u", user)
            pg.fill("#p", pw)
            pg.click("#b")
            pg.wait_for_function("window.Alpine && Alpine.store('app')", timeout=30000)
            time.sleep(3)
            agree = pg.get_by_text("I have read and agree")
            if agree.count() and agree.first.is_visible():
                agree.first.click()
                pg.get_by_role("button", name="Continue").first.click()
                time.sleep(2)
            pg.screenshot(path=str(run / f"{name}-after-signin.png"))
            me = pg.evaluate("fetch('/api/auth/me').then(r => r.json())")
            check(f"{name}: signed in as the first admin",
                  (me.get("principal") or {}).get("role") == "admin", json.dumps(me.get("principal")))
            ctx.close()
        b.close()
    (run / "browser-console.log").write_text("\n".join(console) + "\n")
    (run / "http-failures.log").write_text("\n".join(failed) + "\n")
    check("no browser console errors", not console, "; ".join(console[:3]))
    check("no failed HTTP calls from the UI", not failed, "; ".join(failed[:3]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("install", choices=["container", "pip"])
    ap.add_argument("--version", required=True, help="the release under test")
    ap.add_argument("--ref", default="main", help="pip: the git ref to install")
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep", action="store_true", help="leave it running afterwards")
    a = ap.parse_args(argv)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run = pathlib.Path(a.out) / f"{stamp}_{a.install}_{a.version}"
    run.mkdir(parents=True)
    work = pathlib.Path(tempfile.mkdtemp(prefix="fwh-dc-acc-"))
    data = work / "data"
    data.mkdir()
    user, pw = "acceptance", secrets.token_urlsafe(12)
    env = {"FWH_HOST": "", "MQTT_ENABLED": "false", "ADMIN_USERNAME": user, "ADMIN_PASSWORD": pw,
           "TZ": os.environ.get("TZ", "UTC")}
    checks: list[dict] = []

    def check(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": str(detail)})
        print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail else ""), flush=True)

    proc, what = None, ""
    try:
        if a.install == "container":
            log_cmd, what = start_container(a.version, data, env)
            log_args = ["--log-cmd", " ".join(log_cmd)]
        else:
            proc = start_pip(a.ref, work, env, run / "bridge.log")
            what = f"{REPO}@{a.ref}"
            log_args = ["--log", str(run / "bridge.log")]
        smoke = install_smoke.main([
            "--base", f"http://127.0.0.1:{HTTP_PORT}", "--version", a.version, "--out", str(run / "smoke"),
            "--https", f"https://127.0.0.1:{HTTPS_PORT}", "--cacert", str(data / "tls/bridge.crt"),
            "--user", user, "--password", pw, *log_args])
        for c in json.loads((run / "smoke/summary.json").read_text())["checks"]:
            checks.append(c)
        check("install smoke checks", smoke == 0)
        browser(run, user, pw, check)
    finally:
        if not a.keep:
            if a.install == "container":
                subprocess.run([engine(), "rm", "-f", NAME], capture_output=True)
            elif proc is not None:
                proc.terminate()
                proc.wait(15)
            shutil.rmtree(work, ignore_errors=True)
    passed = sum(c["ok"] for c in checks)
    summary = {"install": a.install, "version": a.version, "source": what, "passed": passed,
               "total": len(checks), "checks": checks}
    (run / "summary.json").write_text(json.dumps(summary, indent=1))
    md = [f"# Standalone acceptance: {a.install} {a.version}", "", f"Source: `{what}`. New install,"
          f" mock gateway, Security on. **{passed}/{len(checks)} checks passed.**", "",
          "| | Check | Detail |", "|---|---|---|"]
    md += [f"| {'✅' if c['ok'] else '❌'} | {c['check']} | {c['detail'].replace('|', '/')} |" for c in checks]
    (run / "summary.md").write_text("\n".join(md) + "\n")
    print(f"\n{passed}/{len(checks)} passed → {run}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
