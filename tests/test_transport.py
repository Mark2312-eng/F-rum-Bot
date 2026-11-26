"""Formatting tests for the in-game city transport module."""
import unittest

from transport import (
    format_transport_history,
    format_transport_routes,
    format_transport_stops,
)


class TransportFormattingTests(unittest.TestCase):
    def test_routes_escape_names_and_show_schedule(self):
        rendered = format_transport_routes([{
            "id": 1,
            "route_code": "A1",
            "name": "<Центральный маршрут>",
            "vehicle_type": "Автобус",
            "interval_minutes": 15,
            "fare": 20,
            "stops": 4,
        }])
        self.assertIn("&lt;Центральный маршрут&gt;", rendered)
        self.assertIn("Интервал: 15 мин.", rendered)
        self.assertIn("Билет: 20 монет", rendered)

    def test_stops_escape_names_and_show_ids(self):
        rendered = format_transport_stops(2, [{
            "stop_order": 1,
            "name": "<Вокзал>",
            "district": "<Центр>",
            "id": 77,
        }])
        self.assertIn("&lt;Вокзал&gt;", rendered)
        self.assertIn("&lt;Центр&gt;", rendered)
        self.assertIn("<code>77</code>", rendered)

    def test_history_escapes_route_and_stop_names(self):
        rendered = format_transport_history([{
            "route_name": "<Маршрут>",
            "from_name": "<Начало>",
            "to_name": "<Конец>",
        }])
        self.assertIn("&lt;Маршрут&gt;", rendered)
        self.assertIn("&lt;Начало&gt;", rendered)
        self.assertIn("&lt;Конец&gt;", rendered)

    def test_empty_results_are_explained(self):
        self.assertIn("Маршруты пока", format_transport_routes([]))
        self.assertIn("нет остановок", format_transport_stops(9, []))
        self.assertIn("история поездок", format_transport_history([]).lower())


if __name__ == "__main__":
    unittest.main()
