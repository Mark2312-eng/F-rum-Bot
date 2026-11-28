"""Small in-process guards for the Telegram admin-panel login flow.

The application runs as a single Render web-service instance. These guards
complement Telegram's signed login payload and HTTPS; they are not a substitute
for edge-level rate limiting when scaling to multiple instances.
"""
from collections import defaultdict, deque
from hashlib import sha256
from time import monotonic


class SlidingWindowLimiter:
    """Bounded per-key sliding-window limiter."""

    def __init__(self, max_keys: int = 5_000) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._max_keys = max_keys

    def allow(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
        now: float | None = None,
    ) -> bool:
        current = monotonic() if now is None else now
        events = self._events.get(key)
        if events is None:
            if len(self._events) >= self._max_keys:
                oldest_key = min(
                    self._events,
                    key=lambda item: self._events[item][-1]
                    if self._events[item] else current,
                )
                self._events.pop(oldest_key, None)
            events = self._events[key]

        cutoff = current - window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= limit:
            return False
        events.append(current)
        return True


class TelegramLoginReplayGuard:
    """Reject reuse of the exact same signed Telegram Login Widget payload."""

    def __init__(self, max_entries: int = 10_000) -> None:
        self._used: dict[str, int] = {}
        self._max_entries = max_entries

    def consume(
        self,
        payload: dict,
        *,
        expires_at: int,
        now: int,
    ) -> bool:
        expired = [key for key, expiry in self._used.items() if expiry < now]
        for key in expired:
            self._used.pop(key, None)
        if len(self._used) >= self._max_entries:
            oldest_key = min(self._used, key=self._used.get)
            self._used.pop(oldest_key, None)

        fingerprint = sha256(
            repr(sorted((str(key), str(value)) for key, value in payload.items())).encode("utf-8")
        ).hexdigest()
        if fingerprint in self._used:
            return False
        self._used[fingerprint] = expires_at
        return True
