"""Tests for the city event calendar and registration codes."""
import unittest
from datetime import datetime, timezone

from city import EVENTS, format_events


class CityEventCalendarTests(unittest.TestCase):
    def test_calendar_lists_all_events_and_signup_codes(self):
        rendered = format_events(datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertIn("Городская ярмарка", rendered)
        self.assertIn("День открытых дверей", rendered)
        self.assertIn("Городской субботник", rendered)
        for code in ("fair", "open_day", "cleanup"):
            self.assertIn(code, rendered)

    def test_event_codes_are_unique(self):
        codes = [event[3] for event in EVENTS]
        self.assertEqual(len(codes), len(set(codes)))

    def test_calendar_uses_utc(self):
        rendered = format_events(datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertIn("UTC", rendered)


if __name__ == "__main__":
    unittest.main()
