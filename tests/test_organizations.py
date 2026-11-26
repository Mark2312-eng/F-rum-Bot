"""Formatting tests for faction and family screens."""
import unittest

from organizations import format_family, format_factions


class OrganizationFormattingTests(unittest.TestCase):
    def test_faction_list_and_current_membership(self):
        rendered = format_factions(
            [{
                "id": 1,
                "name": "<Правительство>",
                "description": "Город & службы",
                "members": 8,
            }],
            {"name": "Правительство", "rank_name": "Новичок"},
        )
        self.assertIn("&lt;Правительство&gt;", rendered)
        self.assertIn("Город &amp; службы", rendered)
        self.assertIn("8", rendered)
        self.assertIn("Новичок", rendered)

    def test_empty_faction_list(self):
        rendered = format_factions([], None)
        self.assertIn("не состоишь во фракции", rendered)

    def test_family_not_joined(self):
        self.assertIn("create Название", format_family(None))

    def test_family_profile(self):
        rendered = format_family({
            "id": 7,
            "name": "<Семья>",
            "members": 3,
            "role": "owner",
        })
        self.assertIn("&lt;Семья&gt;", rendered)
        self.assertIn("7", rendered)
        self.assertIn("3/10", rendered)
        self.assertIn("owner", rendered)


if __name__ == "__main__":
    unittest.main()
