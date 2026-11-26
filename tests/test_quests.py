"""Tests for quest and reputation screen formatting."""
import unittest

from quests import format_quests, format_reputation, reputation_title


class QuestFormattingTests(unittest.TestCase):
    def test_quest_board_displays_rewards_and_status(self):
        rendered = format_quests([{
            "title": "<Первый шаг>",
            "description": "Выполни задание & получи награду.",
            "reward_coins": 150,
            "reward_xp": 100,
            "reward_reputation": 2,
            "completed_at": None,
            "ready": True,
        }])
        self.assertIn("&lt;Первый шаг&gt;", rendered)
        self.assertIn("&amp;", rendered)
        self.assertIn("150 монет", rendered)
        self.assertIn("Можно получить награду", rendered)

    def test_reputation_levels(self):
        self.assertEqual(reputation_title(0), "Новичок")
        self.assertEqual(reputation_title(10), "Известный житель")
        self.assertEqual(reputation_title(50), "Легенда города")

    def test_reputation_profile(self):
        rendered = format_reputation({
            "username": "<Player>",
            "xp": 240,
            "coins": 500,
            "reputation": 12,
        })
        self.assertIn("&lt;Player&gt;", rendered)
        self.assertIn("12", rendered)
        self.assertIn("Известный житель", rendered)

    def test_missing_profile(self):
        self.assertIn("ещё не создан", format_reputation(None))


if __name__ == "__main__":
    unittest.main()
