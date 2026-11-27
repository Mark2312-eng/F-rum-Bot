import pytest

from community_events import parse_event_input, parse_poll_input


def test_parse_event_requires_timezone():
    with pytest.raises(ValueError, match="часовой пояс"):
        parse_event_input("Встреча | 2026-12-01T18:00 | Обсуждение")


def test_parse_event_accepts_timezone():
    title, starts_at, description = parse_event_input(
        "Встреча | 2026-12-01T18:00+03:00 | Обсуждение"
    )
    assert title == "Встреча"
    assert starts_at.utcoffset().total_seconds() == 10800
    assert description == "Обсуждение"


def test_parse_poll_requires_two_options():
    with pytest.raises(ValueError):
        parse_poll_input("Куда идём? | Вариант один")


def test_parse_poll_rejects_duplicate_options():
    with pytest.raises(ValueError, match="повторяться"):
        parse_poll_input("Куда идём? | Парк | парк")


def test_parse_poll_accepts_up_to_six_options():
    question, options = parse_poll_input("Выбор | A | B | C | D | E | F")
    assert question == "Выбор"
    assert len(options) == 6
