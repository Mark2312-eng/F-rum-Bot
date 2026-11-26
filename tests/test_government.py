"""Formatting tests for government departments and service tasks."""
import unittest

from government import format_departments, format_government_roster, format_tasks


class GovernmentFormattingTests(unittest.TestCase):
    def test_department_names_and_descriptions_are_escaped(self):
        rendered = format_departments([{
            "id": 1,
            "name": "<Мэрия>",
            "description": "Город <центр>",
            "employees": 3,
            "base_salary": 150,
        }])
        self.assertIn("&lt;Мэрия&gt;", rendered)
        self.assertIn("Город &lt;центр&gt;", rendered)
        self.assertIn("Базовая зарплата: 150", rendered)

    def test_empty_task_list(self):
        rendered = format_tasks([])
        self.assertIn("Мои служебные поручения", rendered)
        self.assertIn("Поручений пока нет", rendered)

    def test_task_status_and_title_are_rendered_safely(self):
        rendered = format_tasks([{
            "id": 12,
            "title": "<Проверка>",
            "reward_coins": 75,
            "status": "open",
        }])
        self.assertIn("&lt;Проверка&gt;", rendered)
        self.assertIn("75 монет", rendered)
        self.assertIn("открыто", rendered)

    def test_roster_escapes_names_and_positions(self):
        rendered = format_government_roster("<Департамент>", [{
            "user_id": 123,
            "username": "<Игрок>",
            "position": "<Начальник>",
        }])
        self.assertIn("&lt;Департамент&gt;", rendered)
        self.assertIn("&lt;Игрок&gt;", rendered)
        self.assertIn("&lt;Начальник&gt;", rendered)


if __name__ == "__main__":
    unittest.main()
