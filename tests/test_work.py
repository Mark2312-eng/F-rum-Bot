"""Formatting tests for the in-game employment system."""
import unittest

from work import format_employment, format_jobs


class WorkFormattingTests(unittest.TestCase):
    def test_empty_vacancies(self):
        self.assertIn("вакансий нет", format_jobs([]))

    def test_job_names_and_descriptions_are_escaped(self):
        rendered = format_jobs([{
            "id": 1,
            "name": "<Курьер>",
            "description": "Доставка & помощь",
            "reward_coins": 75,
        }])
        self.assertIn("&lt;Курьер&gt;", rendered)
        self.assertIn("Доставка &amp; помощь", rendered)
        self.assertIn("75", rendered)

    def test_unemployed_profile(self):
        self.assertIn("нет работы", format_employment(None))

    def test_employment_profile_escapes_text(self):
        rendered = format_employment({
            "job_name": "<Механик>",
            "rank_name": "Стажёр & помощник",
            "shifts_completed": 4,
            "reward_coins": 100,
        })
        self.assertIn("&lt;Механик&gt;", rendered)
        self.assertIn("Стажёр &amp; помощник", rendered)
        self.assertIn("4", rendered)
        self.assertIn("100", rendered)


if __name__ == "__main__":
    unittest.main()
