"""Formatting tests for МВД and FSB service career screens."""
import unittest

from service import format_service_missions, format_service_profile, format_service_roster


class ServiceFormattingTests(unittest.TestCase):
    def test_empty_profile_prompts_for_application(self):
        rendered = format_service_profile(None)
        self.assertIn("/service apply МВД", rendered)
        self.assertIn("/service apply ФСБ", rendered)

    def test_profile_escapes_faction_and_rank(self):
        rendered = format_service_profile({
            "faction_name": "<МВД>",
            "service_rank": "<Сотрудник>",
            "leader_id": 123,
        })
        self.assertIn("&lt;МВД&gt;", rendered)
        self.assertIn("&lt;Сотрудник&gt;", rendered)
        self.assertIn("<code>123</code>", rendered)

    def test_missions_show_rewards_and_daily_status(self):
        rendered = format_service_missions([{
            "code": "briefing",
            "title": "<Построение>",
            "reward_coins": 45,
            "reward_xp": 15,
            "completed_today": True,
        }])
        self.assertIn("&lt;Построение&gt;", rendered)
        self.assertIn("45 монет", rendered)
        self.assertIn("15 XP", rendered)
        self.assertIn("уже выполнено сегодня", rendered)

    def test_roster_escapes_names_and_ranks(self):
        rendered = format_service_roster(
            {"name": "<ФСБ>"},
            [{"username": "<Игрок>", "user_id": 456, "service_rank": "<Стажёр>"}],
        )
        self.assertIn("&lt;ФСБ&gt;", rendered)
        self.assertIn("&lt;Игрок&gt;", rendered)
        self.assertIn("&lt;Стажёр&gt;", rendered)


if __name__ == "__main__":
    unittest.main()
