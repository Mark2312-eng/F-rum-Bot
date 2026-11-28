from raid_protection import detect_join_burst


def test_join_burst_triggers_at_threshold():
    assert detect_join_burst(-1001, [1, 2, 3, 4], now=100.0) is None
    assert detect_join_burst(-1001, [5], now=101.0) == 5


def test_duplicate_members_are_not_counted_twice():
    assert detect_join_burst(-1002, [1, 1, 2, 2, 3], now=100.0) is None
    assert detect_join_burst(-1002, [3, 4, 5], now=101.0) == 5


def test_join_burst_expires_outside_window():
    assert detect_join_burst(-1003, [1, 2, 3], now=100.0) is None
    assert detect_join_burst(-1003, [4, 5], now=131.0) is None


def test_alert_cooldown_prevents_repeated_notifications():
    assert detect_join_burst(-1004, [1, 2, 3, 4, 5], now=100.0) == 5
    assert detect_join_burst(-1004, [6], now=200.0) is None
    assert detect_join_burst(-1004, [7, 8, 9, 10, 11], now=701.0) == 5
