"""Tests for the one-time VIP Stars shop configuration and presentation."""

import os
import unittest
from unittest.mock import patch

from vip_stars import (
    TIERS,
    build_shop_text,
    _compare_text,
    tier_price,
    vip_shop_keyboard,
)


class VipStarsConfigurationTests(unittest.TestCase):
    def test_unconfigured_prices_disable_checkout_buttons(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(tier_price("silver"))
            self.assertEqual(len(vip_shop_keyboard().inline_keyboard), 5)
            self.assertEqual(
                [button.callback_data for row in vip_shop_keyboard().inline_keyboard for button in row],
                ["vip:detail:silver", "vip:detail:gold", "vip:detail:diamond", "vip:page:compare", "vip:page:status", "vip:page:faq"],
            )

    def test_valid_configured_prices_are_read_from_environment(self):
        values = {
            "VIP_SILVER_PRICE_STARS": "25",
            "VIP_GOLD_PRICE_STARS": "50",
            "VIP_DIAMOND_PRICE_STARS": "100",
        }
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual(tier_price("silver"), 25)
            self.assertEqual(tier_price("gold"), 50)
            self.assertEqual(tier_price("diamond"), 100)
            buttons = [
                button
                for row in vip_shop_keyboard().inline_keyboard
                for button in row
            ]
            self.assertEqual(len(buttons), 6)
            self.assertEqual(
                {button.callback_data for button in buttons},
                {"vip:detail:silver", "vip:detail:gold", "vip:detail:diamond", "vip:page:compare", "vip:page:status", "vip:page:faq"},
            )

    def test_invalid_prices_are_rejected(self):
        for raw in ("0", "-5", "10001", "not-a-number"):
            with self.subTest(raw=raw):
                with patch.dict(os.environ, {"VIP_SILVER_PRICE_STARS": raw}, clear=True):
                    self.assertIsNone(tier_price("silver"))

    def test_unknown_tier_has_no_price(self):
        self.assertIsNone(tier_price("platinum"))

    def test_shop_explains_one_time_term_and_no_autorenewal(self):
        with patch.dict(os.environ, {}, clear=True):
            text = build_shop_text()
        self.assertIn("30 дней", text)
        self.assertIn("Без автопродления", text)
        self.assertIn("временно недоступен", text)

    def test_tiers_have_distinct_progressive_perks(self):
        self.assertEqual(set(TIERS), {"silver", "gold", "diamond"})
        self.assertTrue(any("/vipname" in perk for perk in TIERS["gold"]["perks"]))
        self.assertTrue(any("/viptitle" in perk for perk in TIERS["diamond"]["perks"]))

    def test_comparison_uses_configured_prices(self):
        values = {
            "VIP_SILVER_PRICE_STARS": "31",
            "VIP_GOLD_PRICE_STARS": "62",
            "VIP_DIAMOND_PRICE_STARS": "124",
        }
        with patch.dict(os.environ, values, clear=True):
            text = _compare_text()
        self.assertIn("Silver · 31 ⭐", text)
        self.assertIn("Gold · 62 ⭐", text)
        self.assertIn("Diamond · 124 ⭐", text)
        self.assertNotIn("\\n", text)

    def test_comparison_marks_unconfigured_prices_unavailable(self):
        with patch.dict(os.environ, {}, clear=True):
            text = _compare_text()
        self.assertEqual(text.count("временно недоступен"), 3)
        self.assertNotIn("25 ⭐", text)
        self.assertNotIn("50 ⭐", text)
        self.assertNotIn("100 ⭐", text)


if __name__ == "__main__":
    unittest.main()
