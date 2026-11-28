from panel_security import SlidingWindowLimiter, TelegramLoginReplayGuard


def test_sliding_window_limiter_allows_limit_then_blocks():
    limiter = SlidingWindowLimiter()
    assert limiter.allow("ip", limit=2, window_seconds=60, now=100)
    assert limiter.allow("ip", limit=2, window_seconds=60, now=101)
    assert not limiter.allow("ip", limit=2, window_seconds=60, now=102)
    assert limiter.allow("ip", limit=2, window_seconds=60, now=161)


def test_limiter_tracks_keys_independently():
    limiter = SlidingWindowLimiter()
    assert limiter.allow("user-a", limit=1, window_seconds=60, now=100)
    assert limiter.allow("user-b", limit=1, window_seconds=60, now=100)
    assert not limiter.allow("user-a", limit=1, window_seconds=60, now=101)


def test_telegram_login_payload_cannot_be_replayed():
    guard = TelegramLoginReplayGuard()
    payload = {"id": "123", "auth_date": "1000", "hash": "signed"}
    assert guard.consume(payload, expires_at=1600, now=1001)
    assert not guard.consume(payload, expires_at=1600, now=1002)


def test_replay_guard_expires_old_payloads():
    guard = TelegramLoginReplayGuard()
    payload = {"id": "123", "auth_date": "1000", "hash": "signed"}
    assert guard.consume(payload, expires_at=1100, now=1001)
    assert guard.consume(payload, expires_at=1700, now=1101)
