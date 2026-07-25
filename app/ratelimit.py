"""A small, dependency-free sliding-window rate limiter.

Short-code creation is unauthenticated, so without a limit a single client can
fill the database (and exhaust the code space) as fast as it can open sockets.
This module implements just enough throttling to make that expensive.

Scope and limitations — read before relying on this in production:

* State lives in the process. Behind several workers or replicas each one
  enforces its own budget, so the effective limit is ``workers x limit``. A
  shared store (Redis, or a limiter in the ingress/CDN) is the right answer at
  that point.
* Keys are whatever the caller passes in. :mod:`app.main` keys on the peer
  address from the socket and deliberately ignores ``X-Forwarded-For``: that
  header is attacker-controlled unless a trusted proxy rewrites it, and
  honouring it blindly would let anyone bypass the limit with one extra header.
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict, deque
from typing import Callable, Deque, Tuple

__all__ = ["RateLimiter"]

# Upper bound on the number of distinct keys tracked at once. Without a cap the
# limiter's own bookkeeping becomes a memory-exhaustion vector.
DEFAULT_MAX_TRACKED_KEYS = 10_000


class RateLimiter:
    """Allow at most *max_requests* per *window_seconds* for each key.

    The limiter is thread-safe: FastAPI runs synchronous endpoints in a worker
    thread pool, so concurrent calls to :meth:`allow` are expected.

    A non-positive *max_requests* or *window_seconds* disables the limiter, which
    is how ``RATE_LIMIT_REQUESTS=0`` turns throttling off.
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        max_tracked_keys: int = DEFAULT_MAX_TRACKED_KEYS,
        time_source: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_tracked_keys = max(1, max_tracked_keys)
        self._time = time_source
        self._lock = threading.Lock()
        # key -> timestamps of the calls still inside the window.
        # OrderedDict so the least-recently-used key can be evicted in O(1).
        self._hits: "OrderedDict[str, Deque[float]]" = OrderedDict()
        self._last_prune = time_source()

    @property
    def enabled(self) -> bool:
        return self.max_requests > 0 and self.window_seconds > 0

    def allow(self, key: str) -> Tuple[bool, int]:
        """Record a call for *key*.

        Returns ``(allowed, retry_after_seconds)``. ``retry_after_seconds`` is 0
        when the call is allowed, and otherwise the whole number of seconds until
        the oldest recorded call falls out of the window.
        """
        if not self.enabled:
            return True, 0

        now = self._time()
        cutoff = now - self.window_seconds

        with self._lock:
            self._prune_locked(cutoff, now)

            hits = self._hits.get(key)
            if hits is None:
                hits = deque()
                self._hits[key] = hits

            while hits and hits[0] <= cutoff:
                hits.popleft()

            self._hits.move_to_end(key)

            if len(hits) >= self.max_requests:
                retry_after = max(1, math.ceil(hits[0] + self.window_seconds - now))
                return False, retry_after

            hits.append(now)
            self._evict_locked()
            return True, 0

    def reset(self) -> None:
        """Forget all recorded calls. Used by tests to keep cases independent."""
        with self._lock:
            self._hits.clear()
            self._last_prune = self._time()

    # -- internals ---------------------------------------------------------

    def _prune_locked(self, cutoff: float, now: float) -> None:
        """Drop keys with no calls left in the window.

        Runs at most once per window so that a busy server does not pay an
        O(tracked keys) sweep on every request.
        """
        if now - self._last_prune < self.window_seconds:
            return
        self._last_prune = now
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for key in stale:
            del self._hits[key]

    def _evict_locked(self) -> None:
        """Bound the key table by discarding the least recently seen entries."""
        while len(self._hits) > self.max_tracked_keys:
            self._hits.popitem(last=False)
