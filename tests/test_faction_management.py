"""Tests for faction rank and leadership display."""
import unittest

from organizations import format_factions, format_family


class FactionFormattingTests(unittest.TestCase):
    def test_faction_leader_is_displayed(self):
        rendered = format_factions([{
            "id": 1,
            "name": "ФСБ",
            "description": "Игровая организация",
            "members": 4,
            "leader_id": 12345,
        }], None)
        self.assertIn("Лидер ID: <code>12345</code>", rendered)

    def test_unassigned_leader_is_displayed(self):
        rendered = format_factions([{
            "id": 2,
            "name": "Армия России",
            "description": "Игровая организация",
            "members": 0,
            "leader_id": None,
        }], None)
        self.assertIn("не назначен", rendered)

    def test_member_names_are_html_escaped(self):
        rendered = format_family({
            "id": 1,
            "name": "<Команда>",
            "members": 2,
            "role": "member",
        })
        self.assertIn("&lt;Команда&gt;", rendered)


if __name__ == "__main__":
    unittest.main()
