"""Lever — Rate limiting middleware (GP-12).

CIA Triad Alignment:
  Confidentiality: Prevents credential stuffing / account enumeration via rate limits
  Integrity:       Enforces per-IP request budgets from config.py settings
  Availability:    Protects backend from abuse / DoS; sliding window is memory-efficient

ISO 27001 Controls:
  A.9.4.2   Secure log-on procedures (brute force prevention)
  A.14.1.2  Securing application services (abuse prevention)
  A.12.4.1  Event logging (rate limit violations logged)

Implementation:
  Sliding window counter, same algorithm either way — the store backing
  it is chosen once at import time based on settings.redis_url:
    - unset (the default): per-process in-memory dict, zero external
      dependencies, exactly the original behavior.
    - set: Redis-backed via a sorted set per key, atomic through a Lua
      script (avoids TOCTOU races between the read-count and write-entry
      steps under concurrent requests). Needed once there's more than one
      app instance behind a load balancer — an in-memory limiter lets
      each instance count independently, so the effective limit is
      (configured limit) x (instance count), and every limiter resets on
      every deploy/restart.
  If redis_url is set but the server is unreachable at startup, this
  logs a warning and falls back to the in-memory store rather than
  crashing the app over a rate-limiter dependency.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from threading import Lock
from typing import Dict, List, Tuple

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from config import settings

logger = logging.getLogger("lever.ratelimit")

# ---------------------------------------------------------------------------
# Sliding window rate limiter (in-memory)
# ---------------------------------------------------------------------------

class _SlidingWindowStore:
    """Thread-safe sliding window counter.

    Each key (IP + path prefix) maps to a list of (timestamp, count) entries.
    Entries older than the window are pruned on access.
    """

    def __init__(self):
        self._store: Dict[str, List[Tuple[float, int]]] = defaultdict(list)
        self._lock = Lock()

    def is_allowed(self, key: str, max_requests: int, window_seconds: float) -> Tuple[bool, int, int]:
        """Check if a request is allowed.

        Returns: (allowed, remaining, retry_after_seconds)
        """
        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            # Prune expired entries
            entries = self._store[key]
            self._store[key] = [e for e in entries if e[0] > cutoff]
            entries = self._store[key]

            total = sum(count for _, count in entries)

            if total >= max_requests:
                # Calculate when the oldest entry in window will expire
                if entries:
                    retry_after = int(entries[0][0] + window_seconds - now) + 1
                else:
                    retry_after = int(window_seconds)
                return False, 0, retry_after

            # Record this request
            # Bucket by second to save memory
            current_second = int(now)
            if entries and int(entries[-1][0]) == current_second:
                # Increment existing bucket
                self._store[key][-1] = (entries[-1][0], entries[-1][1] + 1)
            else:
                self._store[key].append((now, 1))

            remaining = max(0, max_requests - total - 1)
            return True, remaining, 0

    def clear(self):
        """Clear all entries (for testing)."""
        with self._lock:
            self._store.clear()


# ---------------------------------------------------------------------------
# Sliding window rate limiter (Redis-backed)
# ---------------------------------------------------------------------------

# Same sliding-window semantics as the in-memory store, implemented with a
# sorted set per key (score = request timestamp) so ZREMRANGEBYSCORE can
# prune everything outside the window in one call. Wrapped in a Lua script
# so the prune-count-and-maybe-add sequence is atomic — without that,
# concurrent requests against the same key could each read the count
# before any of them writes their own entry, letting more requests through
# than the configured limit.
_REDIS_SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local max_requests = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)

if count >= max_requests then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = math.ceil(window)
    if oldest[2] then
        retry_after = math.ceil(tonumber(oldest[2]) + window - now) + 1
    end
    return {0, 0, retry_after}
end

redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, math.ceil(window))
local remaining = max_requests - count - 1
if remaining < 0 then remaining = 0 end
return {1, remaining, 0}
"""


class _RedisSlidingWindowStore:
    """Same interface as _SlidingWindowStore, backed by Redis so every app
    instance shares one counter instead of counting independently."""

    def __init__(self, client):
        self._client = client
        self._script = client.register_script(_REDIS_SLIDING_WINDOW_SCRIPT)

    def is_allowed(self, key: str, max_requests: int, window_seconds: float) -> Tuple[bool, int, int]:
        now = time.time()
        # Unique per call even within the same millisecond, so ZADD always
        # inserts a new member rather than overwriting one with a matching
        # score+member pair.
        member = f"{now}:{uuid.uuid4().hex}"
        allowed, remaining, retry_after = self._script(
            keys=[f"ratelimit:{key}"],
            args=[now, window_seconds, max_requests, member],
        )
        return bool(allowed), int(remaining), int(retry_after)

    def clear(self):
        """No-op — Redis keys expire on their own via EXPIRE; clearing
        everything on demand isn't needed outside of the in-memory store's
        test usage."""
        pass


def _build_store():
    """Pick the rate-limit store once at import time. Falls back to
    in-memory (with a warning) if redis_url is set but unreachable, so a
    Redis outage degrades rate-limit sharing rather than crashing the app."""
    if not settings.redis_url:
        return _SlidingWindowStore()
    try:
        import redis as redis_lib
        client = redis_lib.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=3)
        client.ping()
        logger.info("Rate limiting: using Redis-backed store")
        return _RedisSlidingWindowStore(client)
    except Exception as exc:
        logger.warning(f"REDIS_URL is set but Redis is unreachable ({exc}); falling back to in-memory rate limiting")
        return _SlidingWindowStore()


# Global store instance
_store = _build_store()


# ---------------------------------------------------------------------------
# Route-specific rate limit rules
# ---------------------------------------------------------------------------

# Maps path prefixes to (max_requests, window_minutes) from config
_RATE_RULES: Dict[str, Tuple[int, int]] = {
    "/api/auth/login": (settings.login_rate_limit, settings.login_rate_window_minutes),
    "/api/auth/register": (settings.register_rate_limit, settings.register_rate_window_minutes),
    "/api/auth/resend-verification": (5, 15),
    "/api/auth/reset-password-request": (5, 15),
}

# Global fallback: 120 requests per minute for all API routes
_GLOBAL_API_LIMIT = (120, 1)


def _get_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For behind a reverse proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


# ---------------------------------------------------------------------------
# FastAPI Middleware
# ---------------------------------------------------------------------------

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforce rate limits on API endpoints.

    Adds standard rate limit headers to responses:
      X-RateLimit-Limit:     Maximum requests in window
      X-RateLimit-Remaining: Requests remaining
      X-RateLimit-Reset:     Seconds until window resets (on 429 only)
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Only rate-limit API paths
        if not path.startswith("/api/"):
            return await call_next(request)

        client_ip = _get_client_ip(request)

        # Check route-specific rules first
        matched_rule = None
        for prefix, rule in _RATE_RULES.items():
            if path.startswith(prefix):
                matched_rule = (prefix, rule)
                break

        if matched_rule:
            prefix, (max_req, window_min) = matched_rule
            key = f"{client_ip}:{prefix}"
            allowed, remaining, retry_after = _store.is_allowed(
                key, max_req, window_min * 60
            )
            if not allowed:
                logger.warning(
                    f"Rate limit hit: {client_ip} on {path} "
                    f"({max_req}/{window_min}min)"
                )
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "Too many requests. Please try again later."},
                    headers={
                        "X-RateLimit-Limit": str(max_req),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(retry_after),
                        "Retry-After": str(retry_after),
                    },
                )

        # Global API rate limit
        global_key = f"{client_ip}:global"
        max_req, window_min = _GLOBAL_API_LIMIT
        allowed, remaining, retry_after = _store.is_allowed(
            global_key, max_req, window_min * 60
        )
        if not allowed:
            logger.warning(f"Global rate limit hit: {client_ip} ({max_req}/{window_min}min)")
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Too many requests. Please slow down."},
                headers={
                    "X-RateLimit-Limit": str(max_req),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(retry_after),
                    "Retry-After": str(retry_after),
                },
            )

        response = await call_next(request)

        # Add rate limit headers to successful responses
        if matched_rule:
            _, (limit, _) = matched_rule
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining)

        return response
