"""Shutdown is recorded in the Audit trail: whether the scheduler stopped or was still
running when the bridge stopped waiting, and each held force's release, with whether
the aGate's read-back confirmed it."""
import asyncio

from franklinwh_direct_connect_bridge import battery_control, scheduler_worker


class _Store:
    def __init__(self):
        self.rows = []

    def log_control_event(self, action, **kw):
        self.rows.append((action, kw))


def _run(task_body, store, *, timeout=5.0, release=None):
    async def main():
        stop = asyncio.Event()
        task = asyncio.create_task(task_body(stop))
        await asyncio.sleep(0)
        await scheduler_worker.stop_then_release(stop, task, timeout=timeout,
                                                 release=release or (lambda why: None),
                                                 store=store)
    asyncio.run(main())


def test_a_clean_scheduler_stop_is_audited():
    st = _Store()

    async def tick(stop):
        await stop.wait()

    _run(tick, st)
    rows = [kw for a, kw in st.rows if a == "scheduler_stop"]
    assert rows == [{"source": "shutdown", "detail": "scheduler stop requested",
                     "result": "stopped", "ok": True}]


def test_a_scheduler_still_running_is_audited_as_not_stopped():
    st = _Store()

    async def stuck(stop):
        await asyncio.sleep(60)

    _run(stuck, st, timeout=0.05)
    (row,) = [kw for a, kw in st.rows if a == "scheduler_stop"]
    assert row["ok"] is False and "still running" in row["result"]
    assert "not waited for" in row["result"]


def _held(monkeypatch, out):
    monkeypatch.setattr(battery_control, "held_hosts", lambda: ["10.0.0.9"])
    monkeypatch.setattr(battery_control, "current",
                        lambda host=None: {"active": "Force Discharge"})
    monkeypatch.setattr(battery_control, "_gateway_id", lambda host: "gw-1")
    def execute(cmd, *, host, **kw):
        assert cmd == "Release" and host == "10.0.0.9"
        if isinstance(out, Exception):
            raise out
        return out
    monkeypatch.setattr(battery_control, "execute", execute)


def test_a_confirmed_shutdown_release_is_audited(monkeypatch):
    st = _Store()
    _held(monkeypatch, {"ok": True, "confirmed": True, "result": "released"})
    battery_control.release_held("shutdown", store=st)
    assert st.rows == [("release", {
        "gateway_id": "gw-1", "source": "shutdown",
        "detail": "Force Discharge on 10.0.0.9 (shutdown)",
        "result": "released (confirmed by read-back)", "ok": True})]


def test_an_unconfirmed_shutdown_release_is_audited_as_unconfirmed(monkeypatch):
    st = _Store()
    _held(monkeypatch, {"ok": True, "confirmed": False,
                        "result": "release sent; not confirmed (read-back failed: x)"})
    battery_control.release_held("shutdown", store=st)
    (_, row), = st.rows
    assert row["ok"] is None and "not confirmed" in row["result"]


def test_a_failed_shutdown_release_is_audited_and_the_next_one_still_runs(monkeypatch):
    st = _Store()
    _held(monkeypatch, TimeoutError("no answer"))
    battery_control.release_held("shutdown", store=st)
    (_, row), = st.rows
    assert row["ok"] is False and "no answer" in row["result"]
