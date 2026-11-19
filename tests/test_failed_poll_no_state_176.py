"""#176: a failed poll publishes no state. It used to send a retained state payload built
from the failed summary (empty values) and only then mark the entities offline; now it only
publishes "offline", and the last good state stays retained until a poll succeeds."""
import test_starting_frame_blank as T


class _Pub(T._FakePub):
    avail: list = []

    def publish_availability(self, online):
        _Pub.avail.append(online)


def _failed():
    return {"ok": False, "error": "[Errno 113] Host is unreachable"}


def test_a_failed_poll_publishes_offline_and_no_state(monkeypatch):
    _Pub.avail = []
    monkeypatch.setattr(T, "_FakePub", _Pub)
    monkeypatch.setattr(T.poller, "MqttPublisher", _Pub)
    T._run(monkeypatch, [_failed, _failed])
    assert False in _Pub.avail                     # the failed polls marked it offline
    assert T._FakePub.states, "the polls after it published again"
    assert all(s.get("soc") == 90 for s in T._FakePub.states), \
        "no state built from a failed summary was published"
