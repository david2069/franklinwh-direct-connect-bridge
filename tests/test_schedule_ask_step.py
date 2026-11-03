"""#374 P4: the scheduler's "Ask before continuing" step.

Before the action runs, the enabled notification devices are asked Yes / No. Yes runs it,
No skips this run, and no reply (or nobody could be asked) follows the step's "if no
reply" rule. The wait runs on the Notifier's event loop, so the tick never blocks on it.
The Notifier here is a fake: no Home Assistant is contacted.
"""
import asyncio
import datetime as dt
import threading

import pytest
from fastapi.testclient import TestClient
from franklinwh_ha_notify import NO, YES, Answer

from franklinwh_direct_connect_bridge import actionable, state
from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import scheduler as sch
from franklinwh_direct_connect_bridge.db import MetricsStore

NOW = dt.datetime(2026, 11, 3, 18, 10, tzinfo=dt.timezone(dt.timedelta(hours=10)))
ASK = {"question": "Charge now?", "timeout_min": 5, "if_no_reply": "skip"}


class FakeNotifier:
    """ask_and_wait blocks until the test answers, like a phone that hasn't been tapped."""

    def __init__(self, loop):
        self.loop = loop
        self.calls = []
        self._answer: asyncio.Future | None = None

    async def ask_and_wait(self, event, targets, buttons, *, timeout_s, gateway=None, **values):
        self.calls.append({"event": event, "targets": targets, "verbs": [b.verb for b in buttons],
                           "timeout_s": timeout_s, "gateway": gateway, **values})
        self._answer = self.loop.create_future()
        return await self._answer

    def answer(self, ans: Answer):
        async def tap():
            while self._answer is None:         # the question may still be on its way
                await asyncio.sleep(0)
            self._answer.set_result(ans)
        asyncio.run_coroutine_threadsafe(tap(), self.loop).result(timeout=2)


@pytest.fixture
def notifier(monkeypatch):
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    fake = FakeNotifier(loop)
    monkeypatch.setattr(actionable, "_notifier", fake)
    monkeypatch.setattr(actionable, "_loop", loop)
    monkeypatch.setattr(sch, "ha_snapshot", lambda store: {})
    _clear()
    yield fake
    _clear()
    loop.call_soon_threadsafe(loop.stop)
    t.join(2)


def _clear():
    for d in (sch._asks, sch._window_inside, sch._window_key, sch._gated_day, sch._dwell_since):
        d.clear()


@pytest.fixture
def st(tmp_path):
    return MetricsStore(str(tmp_path / "t.db"))


def _schedule(st, sid="s1", ask=ASK, **spec):
    st.create_schedule(sid=sid, name=f"Rule {sid}", spec={
        "gateway_id": "gw", "fire_at": "18:00", "duration_min": 60, "conditions": [],
        "action": {}, "ha_actions": [], "ask": ask, **spec})


def _tick(st, now=NOW):
    return sch.tick(settings=None, client=None, store=st, state={}, gateway_id="gw", now=now)


def _settle(sid="s1"):
    sch._asks[f"gw:{sid}"]["fut"].result(timeout=2)


def _log(st, sid="s1"):
    return [(r["status"], r["result"]) for r in st.schedule_log(schedule_id=sid)][::-1]


def _occ(st, sid="s1"):
    return st.occurrences_for(sid)[0]


# ── Yes / No / no reply ───────────────────────────────────────────────────────
def test_yes_runs_the_action_after_the_reply(st, notifier):
    _schedule(st)
    assert _tick(st) == [], "the action waits for the answer"
    assert notifier.calls[0]["question"] == "Charge now?"
    assert notifier.calls[0]["verbs"] == [YES, NO] and notifier.calls[0]["timeout_s"] == 300
    assert _tick(st) == [] and len(notifier.calls) == 1, "asked once per run"
    notifier.answer(Answer(YES))
    _settle()
    assert [f["id"] for f in _tick(st)] == ["s1"]
    assert _occ(st)["status"] == "ok"
    assert ("continuing", "answered Yes") in _log(st)
    assert _tick(st) == [] and len(notifier.calls) == 1


def test_no_skips_this_run_and_says_so(st, notifier):
    _schedule(st)
    _tick(st)
    notifier.answer(Answer(NO))
    _settle()
    assert _tick(st) == []
    occ = _occ(st)
    assert occ["status"] == "skipped" and "answered No" in occ["reason"]
    assert ("skipped", "answered No: skipped this run") in _log(st)
    assert _tick(st) == [] and len(notifier.calls) == 1, "not asked again this run"
    assert sch._monitor_state(st.schedule("s1"), "already fired this occurrence", {},
                              True, False) == ("skipped", "answered No: skipped this run")


@pytest.mark.parametrize("rule,fires", [("continue", True), ("skip", False)])
def test_no_reply_follows_the_rule(st, notifier, rule, fires):
    _schedule(st, ask={**ASK, "if_no_reply": rule})
    _tick(st)
    notifier.answer(Answer(None, timed_out=True))
    _settle()
    assert bool(_tick(st)) is fires
    assert _occ(st)["status"] == ("ok" if fires else "skipped")
    assert any(f"(if no reply: {rule})" in r for _, r in _log(st))


def test_nothing_running_to_ask_with_follows_the_rule_at_once(st, monkeypatch):
    monkeypatch.setattr(actionable, "_notifier", None)
    monkeypatch.setattr(sch, "ha_snapshot", lambda store: {})
    _clear()
    _schedule(st, ask={**ASK, "if_no_reply": "continue"})
    _schedule(st, sid="s2", ask={**ASK, "if_no_reply": "skip"})
    assert [f["id"] for f in _tick(st)] == ["s1"]
    assert _occ(st, "s2")["status"] == "skipped"
    assert "nobody could be asked" in _occ(st, "s2")["reason"]
    _clear()


def test_the_wait_does_not_hold_up_other_schedules(st, notifier):
    _schedule(st)
    _schedule(st, sid="s2", ask={})
    assert [f["id"] for f in _tick(st)] == ["s2"], "s2 runs while s1 waits for a reply"


def test_a_schedule_without_the_step_is_never_asked(st, notifier):
    _schedule(st, ask={})
    assert [f["id"] for f in _tick(st)] == ["s1"] and notifier.calls == []


def test_an_always_rule_runs_on_a_later_tick_after_yes(st, notifier):
    _schedule(st, trigger_type="always")
    assert _tick(st) == []
    notifier.answer(Answer(YES))
    _settle()
    assert [f["id"] for f in _tick(st, NOW + dt.timedelta(seconds=15))] == ["s1"]
    assert _tick(st, NOW + dt.timedelta(seconds=30)) == [], "then the rising edge rules again"


def test_targets_are_the_enabled_devices_without_the_notify_prefix(st):
    st.create_notify_device(dev_id="d1", alias="Phone", instance_id="home",
                            service="notify.mobile_app_phone")
    st.create_notify_device(dev_id="d2", alias="Old", instance_id="home",
                            service="mobile_app_old", enabled=False)
    ts = sch._ask_targets(st)
    assert [(t.instance_id, t.service, t.label, t.buttons) for t in ts] == [
        ("home", "mobile_app_phone", "Phone", True)]


# ── saving, checking, export ──────────────────────────────────────────────────
def test_validation():
    assert sch._ask_errors({}) == []
    assert sch._ask_errors(ASK) == []
    errs = sch._ask_errors({"question": "", "timeout_min": 0, "if_no_reply": "maybe"})
    assert len(errs) == 3
    assert sch.validate_spec({"fire_at": "10:00", "ask": {"question": "x"}})


def test_the_step_travels_with_an_export():
    assert sch.portable({"name": "n", "ask": ASK})["ask"] == ASK


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(app_module, "_guard_writes", lambda: None, raising=False)
    state.reset_gateways()
    state.register_gateway("g1", "192.0.2.10", "first")
    yield TestClient(app_module.create_app())
    state.reset_gateways()


def test_the_api_saves_and_refuses_the_step(c):
    body = {"name": "asked", "enabled": False, "fire_at": "10:00", "gateway_id": "g1", "ask": ASK}
    r = c.post("/api/schedules", json=body)
    assert r.status_code == 201 and r.json()["ask"] == ASK
    sid = r.json()["id"]
    assert c.put(f"/api/schedules/{sid}", json={"name": "asked", "enabled": True}).json()["ask"] == ASK
    bad = c.post("/api/schedules", json={**body, "ask": {"question": "x", "timeout_min": 0,
                                                         "if_no_reply": "skip"}})
    assert bad.status_code in (400, 422) and "1 minute" in bad.text


# ── actionable.submit ─────────────────────────────────────────────────────────
def test_submit_runs_on_the_notifier_loop_from_another_thread(monkeypatch):
    async def where():
        return threading.current_thread().name

    monkeypatch.setattr(actionable, "_notifier", None)
    coro = where()
    assert actionable.submit(coro) is None and coro.cr_frame is None, "closed, not leaked"

    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, name="notifier-loop", daemon=True)
    t.start()
    monkeypatch.setattr(actionable, "_notifier", object())
    monkeypatch.setattr(actionable, "_loop", loop)
    try:
        assert actionable.submit(where()).result(timeout=2) == "notifier-loop"
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(2)


def test_start_captures_the_running_loop(tmp_path):
    st = MetricsStore(str(tmp_path / "bridge.db"))

    async def run():
        import types
        await actionable.start(st, types.SimpleNamespace(ha_notify=True))
        loop = asyncio.get_running_loop()
        try:
            assert actionable._loop is loop
        finally:
            await actionable.stop()
    asyncio.run(run())


# ── the editor ────────────────────────────────────────────────────────────────
def test_the_editor_has_the_step_and_saves_it():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    js = (root / "static/js/scheduler_tab.js").read_text()
    html = (root / "templates/tabs/scheduler.html").read_text()
    for field in ('x-model="form.ask.on"', 'x-model="form.ask.question"',
                  'x-model.number="form.ask.timeout_min"', 'x-model="form.ask.if_no_reply"'):
        assert field in html
    assert 'value="skip"' in html and 'value="continue"' in html
    assert "ask: this._askFromForm(this.form.ask)" in js          # saved
    assert "ask: this._askToForm(s.ask)" in js                    # loaded for editing
    assert "ask: this._askToForm(null)" in js                     # a new schedule starts without
