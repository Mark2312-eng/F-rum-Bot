"""Tests for game profile formatting and leaderboard output."""
import unittest

from database import Database
from game import format_achievements, format_game_profile, format_leaderboard


class FakePool:
    def __init__(self):
        self.executed_query = None
        self.executed_args = None

    async def execute(self, query, *args):
        self.executed_query = query
        self.executed_args = args

    async def fetch(self, query, *args):
        return []


class GameFormattingTests(unittest.TestCase):
    def test_achievement_sync_uses_lateral_player_columns(self):
        import asyncio

        database = Database()
        fake_pool = FakePool()
        database.pool = fake_pool
        asyncio.run(database.sync_game_achievements(12))

        self.assertIn("CROSS JOIN LATERAL", fake_pool.executed_query)
        self.assertIn("game_players.xp >= 50", fake_pool.executed_query)
        self.assertEqual(fake_pool.executed_args, (12,))

    def test_profile_escapes_username_and_calculates_level(self):
        profile = {
            "user_id": 12,
            "username": "<Player>",
            "xp": 245,
            "coins": 300,
            "reputation": 4,
            "daily_streak": 2,
        }
        rendered = format_game_profile(profile, [{"achievement_code": "first_steps"}])
        self.assertIn("&lt;Player&gt;", rendered)
        self.assertIn("Уровень: <b>3</b> (45/100 XP)", rendered)
        self.assertIn("300", rendered)
        self.assertIn("Достижений: <b>1</b>", rendered)

    def test_leaderboard_empty_state(self):
        self.assertIn("никто не создал", format_leaderboard([]))

    def test_leaderboard_escapes_names_and_calculates_levels(self):
        rendered = format_leaderboard([
            {"user_id": 1, "username": "<Admin>", "xp": 600},
            {"user_id": 2, "username": "Player", "xp": 100},
        ])
        self.assertIn("&lt;Admin&gt;", rendered)
        self.assertIn("1. <b>", rendered)
        self.assertIn("уровень 7", rendered)

    def test_achievements_show_locked_and_unlocked(self):
        rendered = format_achievements([{"achievement_code": "first_steps"}])
        self.assertIn("✅", rendered)
        self.assertIn("🔒", rendered)


if __name__ == "__main__":
    unittest.main()
