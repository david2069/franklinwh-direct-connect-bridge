"""Accounts, sign-in and sessions (#457 phase 3), and API tokens (phase 4).

Bridge accounts sign in on the HTTPS port. Passwords are argon2id hashes; sessions are
random tokens kept as SHA-256 hashes. 5 failed sign-ins within 15 minutes lock the account
for 60 seconds. The last enabled admin can't be deleted, disabled, demoted or left to
expire. Home Assistant sidebar users have no account here.

An API token belongs to an account and carries its role; it is shown once and kept as a
SHA-256 hash, has an expiry and a last-used time, and can be revoked. ``api`` accounts
have no password: they only call the REST API, with a token.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

log = logging.getLogger(__name__)

ROLES = ("admin", "user", "viewer", "api")
#: The roles that sign in with a password; ``api`` uses tokens only.
PASSWORD_ROLES = ("admin", "user", "viewer")
TOKEN_PREFIX = "fwhdc_"
TOKEN_DAYS = (30, 90, 365)
_USED_EVERY_S = 60
SESSION_S = 30 * 86400
COOKIE = "fwh_session"
LOCK_AFTER = 5
LOCK_WINDOW_S = 15 * 60
LOCK_S = 60
MIN_PASSWORD = 8
_NAME = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")
_ph = PasswordHasher()           # argon2id, the library's defaults
_DUMMY = _ph.hash("not a password")


class AuthError(ValueError):
    """A refusal to show the user as it is."""


def ensure_tables(store) -> None:
    with store._lock:
        store._conn.executescript("""
            CREATE TABLE IF NOT EXISTS auth_users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                role TEXT NOT NULL,
                pw_hash TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                expires_at REAL,
                created_at REAL NOT NULL,
                last_login REAL,
                fail_count INTEGER NOT NULL DEFAULT 0,
                fail_since REAL NOT NULL DEFAULT 0,
                locked_until REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS auth_sessions(
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS auth_log(
                ts REAL NOT NULL, username TEXT NOT NULL, event TEXT NOT NULL, ip TEXT);
            CREATE TABLE IF NOT EXISTS auth_tokens(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                hint TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                last_used REAL);
        """)
        store._conn.commit()


def _rows(store, sql: str, args=()) -> list[dict]:
    with store._lock:
        cur = store._conn.execute(sql, args)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _exec(store, sql: str, args=()) -> int:
    with store._lock:
        cur = store._conn.execute(sql, args)
        store._conn.commit()
        return cur.lastrowid


def _public(u: dict, now: float) -> dict:
    return {"id": u["id"], "username": u["username"], "role": u["role"],
            "enabled": bool(u["enabled"]), "expires_at": u["expires_at"],
            "expired": bool(u["expires_at"] and u["expires_at"] <= now),
            "locked": u["locked_until"] > now, "created_at": u["created_at"],
            "last_login": u["last_login"], "has_password": bool(u["pw_hash"])}


def users(store, now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    return [_public(u, now) for u in _rows(store, "SELECT * FROM auth_users ORDER BY username")]


def _get(store, user_id: int) -> dict:
    r = _rows(store, "SELECT * FROM auth_users WHERE id=?", (user_id,))
    if not r:
        raise AuthError("no such account")
    return r[0]


def _active_admin(u: dict, now: float) -> bool:
    return (u["role"] == "admin" and u["enabled"] and bool(u["pw_hash"])
            and not (u["expires_at"] and u["expires_at"] <= now))


def has_admin(store, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    return any(_active_admin(u, now) for u in _rows(store, "SELECT * FROM auth_users"))


def _check_password(pw) -> str:
    if not isinstance(pw, str) or len(pw) < MIN_PASSWORD:
        raise AuthError(f"the password needs at least {MIN_PASSWORD} characters")
    return pw


def create_user(store, username: str, password: str, role: str,
                expires_at: float | None = None, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    if not isinstance(username, str) or not _NAME.match(username):
        raise AuthError("a username is 1–64 letters, digits or . _ @ -")
    if role not in ROLES:
        raise AuthError(f"the role must be one of {', '.join(ROLES)}")
    if _rows(store, "SELECT id FROM auth_users WHERE username=?", (username,)):
        raise AuthError(f"'{username}' already exists")
    pw_hash = "" if role == "api" else _ph.hash(_check_password(password))
    uid = _exec(store, "INSERT INTO auth_users(username, role, pw_hash, expires_at, created_at) "
                       "VALUES (?,?,?,?,?)", (username, role, pw_hash, expires_at, now))
    record(store, username, f"created ({role})")
    return _public(_get(store, uid), now)


def update_user(store, user_id: int, *, role=None, enabled=None, password=None,
                expires_at=..., now: float | None = None) -> dict:
    """Change an account. Refused when it would leave no enabled admin."""
    now = time.time() if now is None else now
    u = _get(store, user_id)
    new = dict(u)
    if role is not None:
        if role not in ROLES:
            raise AuthError(f"the role must be one of {', '.join(ROLES)}")
        if (role == "api") != (u["role"] == "api"):
            raise AuthError("an api account can't become a password account, or the other "
                            "way round; add a new account")
        new["role"] = role
    if enabled is not None:
        new["enabled"] = 1 if enabled else 0
    if expires_at is not ...:
        new["expires_at"] = expires_at
    if password is not None:
        if new["role"] == "api":
            raise AuthError("an api account has no password; it uses tokens")
        new["pw_hash"] = _ph.hash(_check_password(password))
        new["fail_count"], new["locked_until"] = 0, 0
    if _active_admin(u, now) and not _active_admin(new, now):
        others = [x for x in _rows(store, "SELECT * FROM auth_users WHERE id<>?", (user_id,))
                  if _active_admin(x, now)]
        if not others:
            raise AuthError("this is the last admin; add another admin first")
    _exec(store, "UPDATE auth_users SET role=?, enabled=?, pw_hash=?, expires_at=?, "
                 "fail_count=?, locked_until=? WHERE id=?",
          (new["role"], new["enabled"], new["pw_hash"], new["expires_at"],
           new["fail_count"], new["locked_until"], user_id))
    if not new["enabled"] or new["pw_hash"] != u["pw_hash"]:
        _exec(store, "DELETE FROM auth_sessions WHERE user_id=?", (user_id,))
    changes = [k for k in ("role", "enabled", "expires_at") if new[k] != u[k]]
    if new["pw_hash"] != u["pw_hash"]:
        changes.append("password")
    if changes:
        record(store, u["username"], "changed: " + ", ".join(changes))
    return _public(_get(store, user_id), now)


def delete_user(store, user_id: int, now: float | None = None) -> None:
    now = time.time() if now is None else now
    u = _get(store, user_id)
    if _active_admin(u, now) and not any(
            _active_admin(x, now)
            for x in _rows(store, "SELECT * FROM auth_users WHERE id<>?", (user_id,))):
        raise AuthError("this is the last admin; add another admin first")
    _exec(store, "DELETE FROM auth_sessions WHERE user_id=?", (user_id,))
    _exec(store, "DELETE FROM auth_tokens WHERE user_id=?", (user_id,))
    _exec(store, "DELETE FROM auth_users WHERE id=?", (user_id,))
    record(store, u["username"], "deleted")


def record(store, username: str, event: str, ip: str | None = None) -> None:
    _exec(store, "INSERT INTO auth_log(ts, username, event, ip) VALUES (?,?,?,?)",
          (time.time(), username, event, ip))
    _exec(store, "DELETE FROM auth_log WHERE rowid NOT IN "
                 "(SELECT rowid FROM auth_log ORDER BY ts DESC LIMIT 1000)")


def activity(store, limit: int = 50) -> list[dict]:
    return _rows(store, "SELECT ts, username, event, ip FROM auth_log ORDER BY ts DESC LIMIT ?",
                 (max(1, min(limit, 500)),))


def authenticate(store, username: str, password: str, ip: str | None = None,
                 now: float | None = None) -> dict:
    """The account, or AuthError. The same message for an unknown name and a wrong
    password, so names can't be probed."""
    now = time.time() if now is None else now
    bad = AuthError("wrong username or password")
    r = _rows(store, "SELECT * FROM auth_users WHERE username=?", (username or "",))
    if not r:
        try:
            _ph.verify(_DUMMY, password or "")     # the same time as a real check
        except VerificationError:
            pass
        record(store, str(username or "")[:64], "sign-in failed: unknown name", ip)
        raise bad
    u = r[0]
    if u["locked_until"] > now:
        record(store, u["username"], "sign-in refused: locked", ip)
        raise AuthError(f"too many failed sign-ins; try again in {int(u['locked_until'] - now) + 1} s")
    try:
        ok = bool(u["pw_hash"]) and _ph.verify(u["pw_hash"], password or "")
    except (VerificationError, InvalidHashError):
        ok = False
    if not ok:
        since = u["fail_since"] if now - u["fail_since"] < LOCK_WINDOW_S else now
        count = (u["fail_count"] if since == u["fail_since"] else 0) + 1
        locked = now + LOCK_S if count >= LOCK_AFTER else 0
        _exec(store, "UPDATE auth_users SET fail_count=?, fail_since=?, locked_until=? WHERE id=?",
              (0 if locked else count, since, locked, u["id"]))
        record(store, u["username"], "sign-in failed" + (": locked for 60 s" if locked else ""), ip)
        raise bad
    if not u["enabled"]:
        record(store, u["username"], "sign-in refused: disabled", ip)
        raise AuthError("this account is disabled")
    if u["expires_at"] and u["expires_at"] <= now:
        record(store, u["username"], "sign-in refused: expired", ip)
        raise AuthError("this account has expired")
    if u["role"] not in PASSWORD_ROLES:
        raise bad
    _exec(store, "UPDATE auth_users SET fail_count=0, locked_until=0, last_login=? WHERE id=?",
          (now, u["id"]))
    record(store, u["username"], "signed in", ip)
    return _public(_get(store, u["id"]), now)


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session(store, user_id: int, now: float | None = None) -> str:
    now = time.time() if now is None else now
    token = secrets.token_urlsafe(32)
    _exec(store, "DELETE FROM auth_sessions WHERE expires_at<=?", (now,))
    _exec(store, "INSERT INTO auth_sessions(token_hash, user_id, created_at, expires_at) "
                 "VALUES (?,?,?,?)", (_h(token), user_id, now, now + SESSION_S))
    return token


def session_user(store, token: str | None, now: float | None = None) -> dict | None:
    """The signed-in account for a session cookie, or None (unknown, expired, disabled)."""
    if not token:
        return None
    now = time.time() if now is None else now
    r = _rows(store, "SELECT u.* FROM auth_sessions s JOIN auth_users u ON u.id=s.user_id "
                     "WHERE s.token_hash=? AND s.expires_at>?", (_h(token), now))
    if not r or not r[0]["enabled"] or (r[0]["expires_at"] and r[0]["expires_at"] <= now):
        return None
    return _public(r[0], now)


def end_session(store, token: str | None) -> None:
    if token:
        _exec(store, "DELETE FROM auth_sessions WHERE token_hash=?", (_h(token),))


def ensure_first_admin(store, settings, *, on_addon: bool, security_on: bool) -> str | None:
    """Docker and pip: an admin from ``ADMIN_USERNAME``/``ADMIN_PASSWORD`` while none
    exists; with Security on and neither set, ``admin`` with a generated password, logged
    once. The add-on makes its first admin from the sidebar instead. Returns what was
    done, for the log."""
    if on_addon or has_admin(store):
        return None
    name, pw = settings.admin_username, settings.admin_password
    if name and pw:
        if _rows(store, "SELECT id FROM auth_users WHERE username=?", (name,)):
            return None
        create_user(store, name, pw, "admin")
        log.warning("Security: first admin '%s' created from ADMIN_USERNAME/ADMIN_PASSWORD.", name)
        return "from settings"
    if not security_on or _rows(store, "SELECT id FROM auth_users WHERE username='admin'"):
        return None
    pw = secrets.token_urlsafe(12)
    create_user(store, "admin", pw, "admin")
    log.warning("Security: first admin created. Username: admin  Password: %s  (shown once; "
                "change it under Settings → Admin → Security)", pw)
    return "generated"


def reset_password(store, username: str) -> str:
    """For the command line: a new random password for ``username``, unlocked and enabled.
    A name that doesn't exist yet is created as an admin."""
    pw = secrets.token_urlsafe(12)
    r = _rows(store, "SELECT id FROM auth_users WHERE username=?", (username,))
    if r:
        update_user(store, r[0]["id"], password=pw, enabled=True, expires_at=None)
    else:
        create_user(store, username, pw, "admin")
    record(store, username, "password reset from the command line")
    return pw


# ── API tokens (phase 4) ──────────────────────────────────────────────────────────
def _token_public(r: dict, now: float) -> dict:
    return {"id": r["id"], "user_id": r["user_id"], "username": r.get("username"),
            "role": r.get("role"), "name": r["name"], "hint": r["hint"],
            "created_at": r["created_at"], "expires_at": r["expires_at"],
            "expired": r["expires_at"] <= now, "last_used": r["last_used"]}


def tokens(store, now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    return [_token_public(r, now) for r in _rows(
        store, "SELECT t.*, u.username, u.role FROM auth_tokens t "
               "JOIN auth_users u ON u.id=t.user_id ORDER BY t.created_at DESC")]


def create_token(store, user_id: int, name: str, days: int,
                 now: float | None = None) -> tuple[str, dict]:
    """A new token for an account: ``(token, its listing)``. The token is shown once."""
    now = time.time() if now is None else now
    u = _get(store, user_id)
    name = (name or "").strip()
    if not name or len(name) > 64:
        raise AuthError("give the token a name (1–64 characters), e.g. what will use it")
    if days not in TOKEN_DAYS:
        raise AuthError(f"a token lasts {', '.join(map(str, TOKEN_DAYS))} days")
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    tid = _exec(store, "INSERT INTO auth_tokens(user_id, name, token_hash, hint, created_at, "
                       "expires_at) VALUES (?,?,?,?,?,?)",
                (user_id, name, _h(token), token[-4:], now, now + days * 86400))
    record(store, u["username"], f"token '{name}' created ({days} days)")
    r = _rows(store, "SELECT t.*, u.username, u.role FROM auth_tokens t "
                     "JOIN auth_users u ON u.id=t.user_id WHERE t.id=?", (tid,))[0]
    return token, _token_public(r, now)


def revoke_token(store, token_id: int) -> None:
    r = _rows(store, "SELECT t.name, u.username FROM auth_tokens t JOIN auth_users u "
                     "ON u.id=t.user_id WHERE t.id=?", (token_id,))
    if not r:
        raise AuthError("no such token")
    _exec(store, "DELETE FROM auth_tokens WHERE id=?", (token_id,))
    record(store, r[0]["username"], f"token '{r[0]['name']}' revoked")


def token_user(store, token: str | None, now: float | None = None) -> dict | None:
    """The account a Bearer token belongs to, or None (unknown, expired, revoked, or the
    account disabled or expired)."""
    if not token or not token.startswith(TOKEN_PREFIX):
        return None
    now = time.time() if now is None else now
    r = _rows(store, "SELECT t.id AS tid, t.last_used AS t_used, u.* FROM auth_tokens t "
                     "JOIN auth_users u ON u.id=t.user_id "
                     "WHERE t.token_hash=? AND t.expires_at>?", (_h(token), now))
    if not r or not r[0]["enabled"] or (r[0]["expires_at"] and r[0]["expires_at"] <= now):
        return None
    if not r[0]["t_used"] or now - r[0]["t_used"] >= _USED_EVERY_S:
        _exec(store, "UPDATE auth_tokens SET last_used=? WHERE id=?", (now, r[0]["tid"]))
    return _public(r[0], now)
