"""Formatting tests for expanded player and family rankings."""
import unittest

from game import format_family_leaderboard, format_leaderboard


class ExpandedLeaderboardTests(unittest.TestCase):
    def test_player_rankings_escape_names_and_format_metrics(self):
        players = [{
            "user_id": 1,
            "username": "<Player>",
            "xp": 250,
            "coins": 900,
            "reputation": 12,
        }]
        rendered = format_leaderboard(players, "coins")
        self.assertIn("&lt;Player&gt;", rendered)
        self.assertIn("900 монет", rendered)
        self.assertIn("по монетам", rendered)

    def test_xp_ranking_includes_level(self):
        rendered = format_leaderboard([{
            "user_id": 2,
            "username": "Игрок",
            "xp": 250,
            "coins": 10,
            "reputation": 0,
        }])
        self.assertIn("уровень 3", rendered)
        self.assertIn("250 XP", rendered)

    def test_family_ranking_shows_total_and_member_count(self):
        rendered = format_family_leaderboard([{
            "name": "<Семья>",
            "score": 1250,
            "members": 4,
        }])
        self.assertIn("&lt;Семья&gt;", rendered)
        self.assertIn("1250 XP", rendered)
        self.assertIn("4 участн.", rendered)

    def test_empty_family_ranking(self):
        self.assertIn("Пока нет", format_family_leaderboard([]))


if __name__ == "__main__":
    unittest.main()
