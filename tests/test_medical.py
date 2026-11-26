"""Formatting tests for the in-game medical organization module."""
import unittest

from medical import (
    format_medical_centers,
    format_medical_missions,
    format_medical_profile,
    format_medical_roster,
)


class MedicalFormattingTests(unittest.TestCase):
    def test_centers_escape_names_and_districts(self):
        rendered = format_medical_centers([{
            "id": 2,
            "name": "<Клиника>",
            "district": "<Север>",
            "employees": 4,
        }])
        self.assertIn("&lt;Клиника&gt;", rendered)
        self.assertIn("&lt;Север&gt;", rendered)
        self.assertIn("Сотрудников: 4", rendered)

    def test_empty_profile_explains_application(self):
        rendered = format_medical_profile(None)
        self.assertIn("Городская больница", rendered)
        self.assertIn("/med apply ID", rendered)

    def test_profile_escapes_organization_and_job(self):
        rendered = format_medical_profile({
            "center_name": "<Больница>",
            "district": "Центр",
            "job_title": "<Стажёр>",
            "leader_id": 42,
        })
        self.assertIn("&lt;Больница&gt;", rendered)
        self.assertIn("&lt;Стажёр&gt;", rendered)
        self.assertIn("<code>42</code>", rendered)

    def test_mission_reward_and_daily_state(self):
        rendered = format_medical_missions([{
            "code": "records",
            "title": "<Учебная карточка>",
            "reward_coins": 50,
            "reward_xp": 20,
            "completed_today": True,
        }])
        self.assertIn("&lt;Учебная карточка&gt;", rendered)
        self.assertIn("50 монет", rendered)
        self.assertIn("20 XP", rendered)
        self.assertIn("уже выполнено сегодня", rendered)

    def test_roster_escapes_member_fields(self):
        rendered = format_medical_roster(
            {"faction_name": "<Больница>"},
            [{
                "username": "<Игрок>",
                "user_id": 456,
                "job_title": "<Стажёр>",
                "center_name": "<Центр>",
            }],
        )
        self.assertIn("&lt;Больница&gt;", rendered)
        self.assertIn("&lt;Игрок&gt;", rendered)
        self.assertIn("&lt;Стажёр&gt;", rendered)
        self.assertIn("&lt;Центр&gt;", rendered)


if __name__ == "__main__":
    unittest.main()
