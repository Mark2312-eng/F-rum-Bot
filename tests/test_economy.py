"""Tests for virtual economy message formatting."""
import unittest

from economy import format_catalog, format_inventory


class EconomyFormattingTests(unittest.TestCase):
    def test_catalog_escapes_untrusted_text(self):
        rendered = format_catalog([{
            "name": "<Велосипед>",
            "description": "Транспорт & прогулки",
            "price": 900,
        }], "🚘 <b>Каталог</b>")
        self.assertIn("&lt;Велосипед&gt;", rendered)
        self.assertIn("Транспорт &amp; прогулки", rendered)
        self.assertIn("900", rendered)
        self.assertIn("виртуальными игровыми монетами", rendered)

    def test_empty_catalog(self):
        self.assertIn("ничего нет", format_catalog([], "Каталог"))

    def test_inventory_empty(self):
        self.assertIn("Инвентарь пуст", format_inventory([]))

    def test_inventory_shows_quantity(self):
        rendered = format_inventory([{
            "item_code": "toolkit",
            "name": "Набор инструментов",
            "description": "Для профессии",
            "quantity": 2,
        }])
        self.assertIn("Набор инструментов", rendered)
        self.assertIn("× <b>2</b>", rendered)


if __name__ == "__main__":
    unittest.main()
