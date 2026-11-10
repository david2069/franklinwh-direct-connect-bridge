"""#119 — Unpublish removes everything this bridge published for a gateway, verifies it,
and keeps the gateway unpublished."""
from franklinwh_direct_connect_bridge import config
from franklinwh_direct_connect_bridge.publish import purge


class _Broker:
    def __init__(self, retained):
        self.retained = dict(retained)
        self.published = []


def _factory(broker):
    class _Msg:
        def __init__(self, t, p):
            self.topic, self.payload, self.retain = t, p, True

    class _Info:
        def wait_for_publish(self, timeout=None): pass

    class _C:
        def __init__(self): self.on_message = None
        def connect(self, *a, **k): pass
        def loop_start(self): pass
        def loop_stop(self): pass
        def disconnect(self): pass
        def subscribe(self, t, qos=0):
            if t in broker.retained and self.on_message:
                self.on_message(self, None, _Msg(t, broker.retained[t]))
        def publish(self, t, payload, qos=0, retain=False):
            broker.published.append((t, payload, qos, retain))
            if retain and not payload:
                broker.retained.pop(t, None)
            return _Info()
    return lambda settings, suffix: _C()


def _s():
    return config.get_settings()


def test_topic_list_covers_every_group_state_and_availability():
    s = _s()
    t = purge.topics_for("n1", s)
    assert f"{s.mqtt_prefix}/n1/state" in t and f"{s.mqtt_prefix}/n1/availability" in t
    assert any("/sensor/n1/latency_ms/config" in x for x in t)      # diagnostic group
    assert any("/select/n1/operating_mode/config" in x for x in t)  # controls
    assert all("/n1/" in x for x in t)                              # nothing that isn't ours


def test_purge_removes_ours_verifies_and_leaves_others_alone():
    s = _s()
    ours = purge.topics_for("n1", s)
    other = f"{s.ha_discovery_prefix}/sensor/othernode/soc/config"
    b = _Broker({ours[0]: b"{}", ours[-1]: b"online", ours[-2]: b"{}", other: b"{}"})
    res = purge.purge(s, "n1", wait_s=0, factory=_factory(b))
    assert res["ok"] and res["found"] == 3 and res["removed"] == 3 and res["left"] == []
    assert other in b.retained                                       # foreign topic untouched
    assert all(qos == 1 and retain for _t, _p, qos, retain in b.published)


def test_dry_run_changes_nothing():
    s = _s()
    ours = purge.topics_for("n1", s)
    b = _Broker({ours[0]: b"{}"})
    res = purge.purge(s, "n1", dry_run=True, wait_s=0, factory=_factory(b))
    assert res["dry_run"] and res["would_remove"] == [ours[0]] and b.published == []


def test_a_topic_that_will_not_clear_is_reported_not_hidden():
    s = _s()
    ours = purge.topics_for("n1", s)
    b = _Broker({ours[0]: b"{}"})
    f = _factory(b)

    def stubborn(settings, suffix):
        c = f(settings, suffix)
        real = c.publish
        def publish(t, payload, qos=0, retain=False):
            info = real(t, payload, qos, retain)
            b.retained[t] = b"{}"                    # broker refused to drop it
            return info
        c.publish = publish
        return c
    res = purge.purge(s, "n1", wait_s=0, factory=stubborn)
    assert res["ok"] is False and res["left"] == [ours[0]]
