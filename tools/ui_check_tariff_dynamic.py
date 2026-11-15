#!/usr/bin/env python3
"""Browser check for #651: the tariff editor's Rate type "Dynamic (live)" can be clicked.

    ui_check_tariff_dynamic.py https://127.0.0.1:18799/ --user admin --password ... [--out DIR]

Run it against a throwaway bridge (a fresh DATA_DIR, writes allowed, a mock or unreachable
gateway); it creates a site and two meters when there are none, and adds tariffs. Never point
it at a bridge in use. At a phone (390 px) and a desktop width it:

1. opens Billing & Utilities → Plans & meters → + Add tariff → Energy rates and clicks
   Dynamic (live): the Dynamic box shows, with Provider and the site's Region;
2. switches Provider to Home Assistant price entity (Buy and Feed-in show) and back;
3. saves it, and reads it back: ``pricing.kind == "dynamic"``, source nem, region NSW1;
4. Edit shows it as Dynamic (live);
5. Export, then Import that file onto Meter 2 through the Import dialog: the imported
   tariff is dynamic too.

Needs Playwright with Chrome (``chromium.launch(channel="chrome")``). Exit 0 = all passed.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile

from playwright.sync_api import sync_playwright


def _setup(req, u: str) -> tuple[str, str]:
    """A site with Region AU-NSW, Meter 1 (default) and Meter 2; returns the meter ids."""
    sites = req.get(u + "api/sites").json()["sites"]
    site = next((s for s in sites if s.get("is_default")), None) or req.post(
        u + "api/sites", data={"name": "Home", "region": "AU-NSW", "is_default": True}).json()
    if not site.get("region"):
        req.patch(u + f"api/sites/{site['id']}", data={"region": "AU-NSW"})
    meters = req.get(u + "api/meters").json()["meters"]
    for name, default in (("Meter 1", True), ("Meter 2", False)):
        if not any(m["name"] == name for m in meters):
            req.post(u + "api/meters", data={"site_id": site["id"], "name": name, "is_default": default})
    meters = req.get(u + "api/meters").json()["meters"]
    return (next(m["id"] for m in meters if m["name"] == "Meter 1"),
            next(m["id"] for m in meters if m["name"] == "Meter 2"))


def _open_plans(page, u: str) -> None:
    page.goto(u)
    page.wait_for_load_state("networkidle")
    page.evaluate("() => { Alpine.store('app').showDisclaimer = false;"
                  " Alpine.store('app').activeTab = 'energy_costs'; }")
    page.wait_for_timeout(600)
    page.evaluate("() => document.querySelectorAll('.fixed.inset-0').forEach(e => {"
                  " if (!e.closest('[role=dialog]') && !e.matches('[data-testid]')"
                  " && getComputedStyle(e).display !== 'none') e.remove(); })")
    page.get_by_role("button", name="Plans & meters").click()
    page.wait_for_timeout(600)


def run(u: str, user: str, pw: str, width: int, out: pathlib.Path, log) -> None:
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        ctx = b.new_context(ignore_https_errors=True, viewport={"width": width, "height": 900},
                            accept_downloads=True)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        assert page.request.post(u + "api/auth/login", data={"username": user, "password": pw}).ok
        m1, m2 = _setup(page.request, u)
        for t in page.request.get(u + "api/tariffs").json()["tariffs"]:   # a clean run
            page.request.delete(u + f"api/tariffs/{t['id']}")
        if not page.request.get(u + "api/utilities").json()["utilities"]:
            page.request.post(u + "api/utilities", data={"name": "Amber Electric", "network_dnsp": "Ausgrid"})
        _open_plans(page, u)
        meter1 = page.locator("[data-testid=meter-plan]").first
        meter1.locator("[data-testid=meter-plan-new]").click()
        page.get_by_role("button", name="Energy rates").click()
        dyn = page.get_by_role("button", name="Dynamic (live)")
        dyn.click(timeout=5000)                                          # 1. the click #651 lost
        box = page.locator("text=Dynamic — priced at the live rate")
        box.wait_for(state="visible", timeout=3000)
        assert "emerald" in (dyn.get_attribute("class") or "")
        region = page.locator("[data-testid=tariff-nem-region]")
        assert region.is_visible() and "NSW1" in region.inner_text(), region.inner_text()
        log(f"[{width}] 1. Dynamic (live) selected; Region: {region.inner_text()!r}")
        page.screenshot(path=str(out / f"651_{width}_dynamic.png"))
        page.get_by_role("button", name="AusNEM (AEMO spot)").click()      # 2. provider
        page.get_by_role("button", name="Home Assistant price entity").click()
        page.locator("text=choose price entity…").wait_for(state="visible", timeout=3000)
        assert page.locator("text=none (use buy price)").is_visible()
        log(f"[{width}] 2. Provider Home Assistant: Buy and Feed-in show")
        page.get_by_role("button", name="Home Assistant price entity").click()
        page.get_by_role("button", name="AusNEM (AEMO spot)").last.click()
        page.get_by_placeholder("AGL Home").fill("Amber dynamic")       # 3. save
        page.get_by_role("button", name="Save", exact=True).last.click()
        page.wait_for_timeout(1000)
        ts = page.request.get(u + "api/tariffs").json()["tariffs"]
        t = next(x for x in ts if x["name"] == "Amber dynamic")
        dn = t["pricing"].get("dynamic") or {}
        assert t["pricing"].get("kind") == "dynamic", t["pricing"]
        assert dn.get("source") == "nem" and dn.get("region") == "NSW1", dn
        assert t.get("meter_id") == m1
        log(f"[{width}] 3. saved: kind={t['pricing']['kind']} dynamic={json.dumps(dn)}")
        meter1.get_by_role("button", name="Edit", exact=True).click()   # 4. edit shows it
        page.get_by_role("button", name="Energy rates").click()
        box.wait_for(state="visible", timeout=3000)
        assert "emerald" in (page.get_by_role("button", name="Dynamic (live)").get_attribute("class") or "")
        log(f"[{width}] 4. Edit shows Dynamic (live)")
        assert not errors, errors                                         # none up to here
        page.get_by_role("button", name="Cancel", exact=True).last.click()
        with page.expect_download() as dl:                                # 5. export → import
            meter1.get_by_role("button", name="Export", exact=True).click()
        f = out / f"651_{width}_export.json"
        dl.value.save_as(str(f))
        assert json.loads(f.read_text())["profile"]["pricing"]["kind"] == "dynamic"
        page.locator("[data-testid=meter-plan]").nth(1).locator("[data-testid=meter-plan-import]").click()
        page.locator("[data-testid=tariff-import-paste]").fill(f.read_text())
        page.locator("[data-testid=tariff-import-check]").click()
        page.wait_for_timeout(600)
        page.locator("[data-testid=tariff-import-apply]").click()
        page.locator("[data-testid=tariff-import-done]").wait_for(state="visible", timeout=3000)
        page.locator("[data-testid=tariff-import-done-close]").click()
        ts = page.request.get(u + "api/tariffs").json()["tariffs"]
        imp = next(x for x in ts if x.get("meter_id") == m2)
        assert imp["pricing"].get("kind") == "dynamic" and imp["pricing"]["dynamic"] == t["pricing"]["dynamic"], imp
        log(f"[{width}] 5. Export → Import onto Meter 2: kind={imp['pricing']['kind']} "
            f"dynamic={json.dumps(imp['pricing']['dynamic'])}")
        if errors:   # Cancel's teardown of the rate inputs; not #651's, reported separately
            log(f"[{width}] note: page errors after Cancel: {sorted(set(errors))}")
        b.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("url")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    u = a.url.rstrip("/") + "/"
    out = pathlib.Path(a.out or tempfile.mkdtemp(prefix="ui651_"))
    out.mkdir(parents=True, exist_ok=True)
    ok = True
    for w in (390, 1280):
        try:
            run(u, a.user, a.password, w, out, print)
            print(f"[{w}] PASS")
        except Exception as e:  # noqa: BLE001 — report and keep the other width
            ok = False
            print(f"[{w}] FAIL: {type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}")
    print("evidence:", out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
