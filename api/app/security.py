"""Protection against abuse: rate limit, dashboard lockout, customer keys.

The counters live in process memory on purpose. They are not user data, and
losing them on a restart only resets the limits."""
import hashlib
import hmac
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

from . import config, db

_lock = threading.Lock()
_hits: dict[str, deque] = {}
_fails: dict[str, list] = {}  # ip -> [wrong attempts, locked until]


def client_ip(request: Request) -> str:
    """The real sender, taken from the headers the hosting proxy adds."""
    h = request.headers
    ip = h.get("cf-connecting-ip") or h.get("true-client-ip") or h.get("x-forwarded-for", "").split(",")[0].strip()
    return ip or (request.client.host if request.client else "unknown")


def too_many_requests(request: Request) -> bool:
    """True when this sender has used up its messages for the last minute."""
    ip, now = client_ip(request), time.time()
    with _lock:
        if len(_hits) > 5000:  # keep the table small
            _hits.clear()
        q = _hits.setdefault(ip, deque())
        while q and q[0] <= now - 60:
            q.popleft()
        if len(q) >= config.RATE_LIMIT_PER_MIN:
            return True
        q.append(now)
        return False


def check_admin(request: Request, token: str) -> None:
    """Checks the dashboard password. Five wrong tries lock that sender out for 15 minutes."""
    ip, now = client_ip(request), time.time()
    with _lock:
        count, locked_until = _fails.get(ip, [0, 0.0])
        if locked_until > now:
            raise HTTPException(status_code=429, detail="Too many wrong passwords. Try again in 15 minutes.")
        ok = bool(config.ADMIN_PASSWORD) and hmac.compare_digest(token.encode(), config.ADMIN_PASSWORD.encode())
        if ok:
            _fails.pop(ip, None)
            return
        count += 1
        _fails[ip] = [0, now + config.ADMIN_LOCK_SECONDS] if count >= config.ADMIN_MAX_FAILS else [count, 0.0]
    raise HTTPException(status_code=401, detail="Wrong admin password")


def check_user(user_id: str, key: str) -> None:
    """Website customers (ids that start with "web-") must send their secret key.

    The first key used with an id claims it. After that, only that key works,
    so knowing someone's id is not enough to read their orders or memory.
    Other ids stay open, because the brief says /chat must work without login."""
    if not user_id.startswith("web-"):
        return
    if len(key) < 16:
        raise HTTPException(status_code=403, detail="This customer needs a key")
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    db.init()
    claimed = db.query(
        "INSERT INTO user_keys (user_id, key_hash) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING RETURNING user_id",
        (user_id, key_hash),
    )
    if claimed:
        return
    stored = db.query("SELECT key_hash FROM user_keys WHERE user_id = %s", (user_id,))[0]["key_hash"]
    if not hmac.compare_digest(stored, key_hash):
        raise HTTPException(status_code=403, detail="That customer name is already used on another device")
