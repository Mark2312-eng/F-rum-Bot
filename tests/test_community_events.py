import unittest

from community_events import parse_event_input, parse_poll_input


class CommunityEventParsingTests(unittest.TestCase):
    def test_event_requires_timezone(self):
        with self.assertRaisesRegex(ValueError, "часовой пояс"):
            parse_event_input("Встреча | 2026-12-01T18:00 | Обсуждение")

    def test_event_accepts_timezone(self):
        title, starts_at, description = parse_event_input(
            "Встреча | 2026-12-01T18:00+03:00 | Обсуждение"
        )
        self.assertEqual(title, "Встреча")
        self.assertEqual(starts_at.utcoffset().total_seconds(), 10800)
        self.assertEqual(description, "Обсуждение")

    def test_poll_requires_two_options(self):
        with self.assertRaises(ValueError):
            parse_poll_input("Куда идём? | Вариант один")

    def test_poll_rejects_duplicate_options(self):
        with self.assertRaisesRegex(ValueError, "повторяться"):
            parse_poll_input("Куда идём? | Парк | парк")

    def test_poll_accepts_six_options(self):
        question, options = parse_poll_input("Выбор | A | B | C | D | E | F")
        self.assertEqual(question, "Выбор")
        self.assertEqual(len(options), 6)


if __name__ == "__main__":
    unittest.main()
