"""Formatting tests for the in-game education system."""
import unittest

from education import (
    format_education_courses,
    format_education_institutions,
    format_education_profile,
    format_education_roster,
)


class EducationFormattingTests(unittest.TestCase):
    def test_institutions_escape_untrusted_fields(self):
        rendered = format_education_institutions([{
            "id": 1,
            "name": "<Школа>",
            "institution_type": "<Школа>",
            "district": "<Центр>",
            "students": 12,
        }])
        self.assertIn("&lt;Школа&gt;", rendered)
        self.assertIn("&lt;Центр&gt;", rendered)
        self.assertIn("Учащихся: 12", rendered)

    def test_empty_profile_explains_enrollment(self):
        rendered = format_education_profile(None)
        self.assertIn("Городское образование", rendered)
        self.assertIn("/edu enroll ID", rendered)

    def test_profile_escapes_institution_fields(self):
        rendered = format_education_profile({
            "institution_name": "<Университет>",
            "institution_type": "Университет",
            "district": "Центр",
            "user_id": 123,
        })
        self.assertIn("&lt;Университет&gt;", rendered)
        self.assertIn("<code>123</code>", rendered)

    def test_courses_show_rewards_and_status(self):
        rendered = format_education_courses([{
            "code": "history",
            "title": "<История города>",
            "course_type": "lesson",
            "reward_coins": 35,
            "reward_xp": 15,
            "completed_today": True,
        }])
        self.assertIn("&lt;История города&gt;", rendered)
        self.assertIn("35 монет", rendered)
        self.assertIn("15 XP", rendered)
        self.assertIn("засчитано сегодня", rendered)

    def test_roster_escapes_student_names(self):
        rendered = format_education_roster(
            {"name": "<Колледж>"},
            [{"username": "<Ученик>", "user_id": 456}],
        )
        self.assertIn("&lt;Колледж&gt;", rendered)
        self.assertIn("&lt;Ученик&gt;", rendered)
        self.assertIn("<code>456</code>", rendered)


if __name__ == "__main__":
    unittest.main()
