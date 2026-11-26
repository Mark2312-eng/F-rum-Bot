"""Formatting tests for the in-game taxi module."""
import unittest

from taxi import format_taxi_history, format_taxi_orders, format_taxi_rating


class TaxiFormattingTests(unittest.TestCase):
    def test_open_orders_escape_names_and_show_fare(self):
        rendered = format_taxi_orders([{
            "id": 7,
            "route_name": "<Центральный маршрут>",
            "passenger_name": "<Игрок>",
            "from_name": "<Вокзал>",
            "to_name": "<Университет>",
            "fare": 50,
        }])
        self.assertIn("Заказ №7", rendered)
        self.assertIn("&lt;Центральный маршрут&gt;", rendered)
        self.assertIn("&lt;Игрок&gt;", rendered)
        self.assertIn("&lt;Вокзал&gt;", rendered)
        self.assertIn("50 монет", rendered)

    def test_history_formats_status_and_escapes_stops(self):
        rendered = format_taxi_history([{
            "id": 9,
            "status": "completed",
            "route_name": "A1",
            "from_name": "<Центр>",
            "to_name": "<Парк>",
            "fare": 40,
            "driver_name": "<Водитель>",
        }])
        self.assertIn("Завершён", rendered)
        self.assertIn("&lt;Центр&gt;", rendered)
        self.assertIn("&lt;Парк&gt;", rendered)
        self.assertIn("&lt;Водитель&gt;", rendered)

    def test_rating_handles_empty_and_populated_results(self):
        self.assertIn("Пока нет оценок", format_taxi_rating({"ratings": 0, "average_rating": None}))
        rendered = format_taxi_rating({"ratings": 4, "average_rating": 4.5})
        self.assertIn("4.50/5", rendered)
        self.assertIn("Количество оценок: <b>4</b>", rendered)

    def test_empty_lists_are_explained(self):
        self.assertIn("Свободных заказов", format_taxi_orders([]))
        self.assertIn("История поездок", format_taxi_history([]))


if __name__ == "__main__":
    unittest.main()
