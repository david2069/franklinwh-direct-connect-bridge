"""One shared pattern for outward calls: deadline, retry, outcome, log, notify.

Every call that leaves this process — aGate TCP/9000, Modbus TCP/502, the cloud
REST API, MQTT, Home Assistant — fails in the same three ways, and the bridge was
handling each one ad hoc:

* **swallow-and-continue** — the outcome is lost. The scheduler marked a window
  fired after its action failed, so a two-second Wi-Fi blip burned the whole
  occurrence silently.
* **unbounded wait** — no deadline, so one slow call stalls a poll cycle.
* **no transient/permanent split** — nothing said "retry me" versus "give up",
  so nothing could retry safely.

And a fourth that is a safety matter rather than hygiene: there was no
**UNKNOWN** outcome. A write that times out *after the request left* has not
failed — nobody knows what it did. That distinction matters most for battery
dispatch, where this firmware's hardware revert timer is cosmetic and the
software watchdog is the only thing that ends a force. An UNKNOWN dispatch means
the battery may be moving while the bridge believes nothing is running, so it is
reported louder than a failure, never retried blind, and always audited.

Scope: use at BOUNDARIES — device I/O, cloud, Modbus, MQTT, scheduler actions and
UI-initiated writes. Not for in-process logic, and not a replacement for the
"never kill the poll loop" guards further in.

The module is deliberately dependency-free so it can be lifted into the Modbus
bridge (or franklinwh-hybrid) unchanged.
"""
from __future__ import annotations

import logging
import random
import socket
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

log = logging.getLogger(__name__)


class Verdict(str, Enum):
    """What actually happened. ``UNKNOWN`` is the one that matters for writes."""

    OK = "ok"
    FAILED = "failed"        # it did not happen; safe to retry
    UNKNOWN = "unknown"      # it may have happened; NEVER retried automatically
    SKIPPED = "skipped"      # preconditions unmet; nothing was attempted


#: Transport-level faults: the call did not get a useful answer, and trying again
#: is reasonable. Wi-Fi drops, a rebooting aGate and a busy broker all land here.
TRANSIENT: tuple[type[BaseException], ...] = (
    TimeoutError, ConnectionError, socket.timeout, socket.gaierror, OSError,
)

#: Caller or device said no. Retrying repeats the same answer.
PERMANENT: tuple[type[BaseException], ...] = (
    ValueError, TypeError, KeyError, NotImplementedError, PermissionError,
)


def is_transient(exc: BaseException) -> bool:
    """Classify a failure. PERMANENT wins: several of those subclass OSError."""
    if isinstance(exc, PERMANENT):
        return False
    return isinstance(exc, TRANSIENT)


def _arrived(exc: BaseException) -> bool:
    """Did the request plausibly reach the device before this failure?

    A refused connection or a DNS failure means it never left, so the call
    definitely did not happen — FAILED, and safe to retry. A timeout means the
    bytes may well have been delivered and only the answer was lost, so for a
    write that is UNKNOWN.
    """
    if isinstance(exc, (ConnectionRefusedError, socket.gaierror)):
        return False
    return isinstance(exc, (TimeoutError, socket.timeout)) or not isinstance(exc, ConnectionError)


@dataclass(frozen=True)
class RetryPolicy:
    """How hard to try. ``deadline_s`` bounds the whole call including sleeps."""

    attempts: int = 3
    base_delay_s: float = 1.0
    max_delay_s: float = 15.0
    deadline_s: float = 60.0
    jitter: float = 0.25

    #: Writes are not retried on UNKNOWN; a second force-charge after an
    #: ambiguous first one is how you end up dispatching twice.
    retry_unknown: bool = False

    def delay_for(self, attempt: int) -> float:
        """Exponential backoff with jitter, so N gateways don't retry in lockstep."""
        raw = min(self.max_delay_s, self.base_delay_s * (2 ** max(0, attempt - 1)))
        return max(0.0, raw * (1.0 + random.uniform(-self.jitter, self.jitter)))


#: Sensible defaults by call shape. A read may be retried freely; a write may not
#: be retried once its outcome is ambiguous.
READ = RetryPolicy(attempts=3, base_delay_s=1.0, deadline_s=45.0)
WRITE = RetryPolicy(attempts=2, base_delay_s=2.0, deadline_s=30.0, retry_unknown=False)
#: Scheduler actions get the window to themselves — the caller passes the window
#: end as the deadline, so retrying stops when the window does.
DISPATCH = RetryPolicy(attempts=5, base_delay_s=5.0, max_delay_s=60.0, deadline_s=300.0)


@dataclass
class Outcome:
    """The structured result every boundary call returns.

    Replaces the free-text results the scheduler used to substring-match on
    (``"failed" not in result``), which is why a failed action could still be
    recorded as fired.
    """

    verdict: Verdict
    action: str
    target: str = ""
    detail: str = ""
    attempts: int = 0
    elapsed_s: float = 0.0
    error: str = ""
    value: Any = None
    meta: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.verdict is Verdict.OK

    @property
    def needs_attention(self) -> bool:
        """FAILED and UNKNOWN both warrant telling someone; UNKNOWN more so."""
        return self.verdict in (Verdict.FAILED, Verdict.UNKNOWN)

    def render(self) -> str:
        """One-line human form, for logs, the audit trail and the schedule history."""
        bits = [f"{self.action}"]
        if self.target:
            bits.append(f"[{self.target}]")
        bits.append(f"-> {self.verdict.value}")
        if self.detail:
            bits.append(f"· {self.detail}")
        if self.error:
            bits.append(f"· {self.error}")
        if self.attempts > 1:
            bits.append(f"· {self.attempts} attempts")
        return " ".join(bits)

    def as_dict(self) -> dict:
        return {"verdict": self.verdict.value, "action": self.action, "target": self.target,
                "detail": self.detail, "attempts": self.attempts,
                "elapsed_s": round(self.elapsed_s, 3), "error": self.error, **self.meta}


def call(fn: Callable[[], Any], *, action: str, target: str = "", policy: RetryPolicy = READ,
         write: bool = False, audit: Callable[..., None] | None = None,
         notifier: Any = None, deadline_s: float | None = None) -> Outcome:
    """Run ``fn`` under a deadline with classified retries, and return an Outcome.

    ``write=True`` changes the failure semantics, not the retry count: an
    ambiguous failure becomes UNKNOWN rather than FAILED, and UNKNOWN is not
    retried unless the policy explicitly allows it.

    Never raises. The whole point is that the caller gets a verdict it can branch
    on instead of an exception it will swallow.
    """
    started = time.monotonic()
    budget = policy.deadline_s if deadline_s is None else max(0.0, deadline_s)
    last: BaseException | None = None
    attempt = 0

    while attempt < max(1, policy.attempts):
        attempt += 1
        if time.monotonic() - started >= budget:
            break
        try:
            value = fn()
        except BaseException as exc:  # noqa: BLE001 — classified below, never re-raised
            last = exc
            transient = is_transient(exc)
            ambiguous = write and _arrived(exc)
            log.debug("%s[%s] attempt %d/%d failed (%s%s): %s", action, target, attempt,
                      policy.attempts, "transient" if transient else "permanent",
                      ", ambiguous" if ambiguous else "", exc)
            if ambiguous and not policy.retry_unknown:
                out = _finish(Verdict.UNKNOWN, action, target, attempt, started, exc,
                              detail="write may have been applied; not retried")
                return _report(out, audit=audit, notifier=notifier, write=write)
            if not transient:
                out = _finish(Verdict.FAILED, action, target, attempt, started, exc)
                return _report(out, audit=audit, notifier=notifier, write=write)
            remaining = budget - (time.monotonic() - started)
            if attempt >= policy.attempts or remaining <= 0:
                break
            time.sleep(min(policy.delay_for(attempt), remaining))
            continue
        out = Outcome(verdict=Verdict.OK, action=action, target=target, attempts=attempt,
                      elapsed_s=time.monotonic() - started, value=value)
        if isinstance(value, dict) and value.get("detail"):
            out.detail = str(value["detail"])
        return _report(out, audit=audit, notifier=notifier, write=write)

    verdict = Verdict.UNKNOWN if (write and last is not None and _arrived(last)) else Verdict.FAILED
    out = _finish(verdict, action, target, attempt, started, last,
                  detail="deadline exceeded" if last is None else "")
    return _report(out, audit=audit, notifier=notifier, write=write)


def _finish(verdict: Verdict, action: str, target: str, attempts: int, started: float,
            exc: BaseException | None, detail: str = "") -> Outcome:
    return Outcome(verdict=verdict, action=action, target=target, attempts=attempts,
                   elapsed_s=time.monotonic() - started, detail=detail,
                   error=f"{type(exc).__name__}: {exc}" if exc else "")


def _report(out: Outcome, *, audit, notifier, write: bool) -> Outcome:
    """One log line per completed call, plus audit and notification for writes.

    Severity follows the verdict, so UNKNOWN is never buried at INFO: it is the
    state a human has to resolve.
    """
    line = out.render()
    if out.verdict is Verdict.UNKNOWN:
        log.error("UNKNOWN OUTCOME · %s", line)
    elif out.verdict is Verdict.FAILED:
        log.warning("%s", line)
    elif out.attempts > 1:
        log.info("recovered after retry · %s", line)
    else:
        log.debug("%s", line)

    if write and audit is not None:
        try:
            audit(out.action, detail=out.target, result=out.render(), ok=out.ok)
        except Exception:  # noqa: BLE001 — auditing must never break the call
            log.debug("audit hook failed for %s", out.action, exc_info=True)

    if write and out.needs_attention and notifier is not None:
        try:
            title = ("FranklinWH — outcome UNKNOWN" if out.verdict is Verdict.UNKNOWN
                     else "FranklinWH — action failed")
            notifier.notify(title, out.render())
        except Exception:  # noqa: BLE001 — notifying must never break the call
            log.debug("notify hook failed for %s", out.action, exc_info=True)
    return out
