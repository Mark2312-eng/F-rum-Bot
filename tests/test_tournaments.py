"""Tests for family tournament output formatting."""
import unittest

from tournaments import format_tournaments


class TournamentFormattingTests(unittest.TestCase):
    def test_empty_tournament_list(self):
        rendered = format_tournaments([])
        self.assertIn("Турниры семей", rendered)
        self.assertIn("Пока турниров нет", rendered)

    def test_open_tournament(self):
        rendered = format_tournaments([{
            "id": 7,
            "name": "<Кубок Москвы>",
            "status": "open",
            "family_count": 3,
            "prize_coins": 1200,
            "winner_name": None,
        }])
        self.assertIn("&lt;Кубок Москвы&gt;", rendered)
        self.assertIn("Регистрация", rendered)
        self.assertIn("Семей: 3", rendered)
        self.assertIn("1200 игровых монет", rendered)

    def test_finished_tournament_shows_winner(self):
        rendered = format_tournaments([{
            "id": 8,
            "name": "Финал",
            "status": "finished",
            "family_count": 2,
            "prize_coins": 500,
            "winner_name": "<Победители>",
        }])
        self.assertIn("Завершён", rendered)
        self.assertIn("&lt;Победители&gt;", rendered)


if __name__ == "__main__":
    unittest.main()
