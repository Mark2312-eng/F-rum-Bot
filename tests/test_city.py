"""Tests for phone, city directory and event formatting."""
import unittest
from datetime import datetime, timezone

from city import format_city, format_events, format_places


class CityFormattingTests(unittest.TestCase):
    def test_city_map_lists_zones(self):
        rendered = format_city()
        self.assertIn("Центр", rendered)
        self.assertIn("Промзона", rendered)

    def test_places_include_contact_details(self):
        rendered = format_places()
        self.assertIn("Мэрия", rendered)
        self.assertIn("Больница", rendered)
        self.assertIn("UTC", rendered)

    def test_events_have_deterministic_schedule(self):
        now = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
        rendered = format_events(now)
        self.assertIn("Городская ярмарка", rendered)
        self.assertIn("26.11.2026 02:00 UTC", rendered)
        self.assertIn("игровые события", rendered)


if __name__ == "__main__":
    unittest.main()
