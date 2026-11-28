import unittest
from datetime import datetime, timezone
from community_rewards import contest_card, normalize_promo_code, parse_contest_input


class CommunityRewardsParsingTests(unittest.TestCase):
    def test_contest_requires_timezone(self):
        with self.assertRaisesRegex(ValueError, "часовой пояс"):
            parse_contest_input("Тест | 2026-12-20T18:00 | 3 | VIP")

    def test_contest_parses_valid_input(self):
        title, ends_at, winners, prize = parse_contest_input(
            "Зимний розыгрыш | 2027-12-20T18:00+03:00 | 5 | VIP Gold на 30 дней"
        )
        self.assertEqual(title, "Зимний розыгрыш")
        self.assertEqual(ends_at.utcoffset().total_seconds(), 10800)
        self.assertEqual(winners, 5)
        self.assertEqual(prize, "VIP Gold на 30 дней")

    def test_contest_rejects_past_deadline(self):
        with self.assertRaisesRegex(ValueError, "будущем"):
            parse_contest_input("Старый конкурс | 2020-01-01T00:00+00:00 | 1 | Приз")

    def test_contest_rejects_invalid_winner_count(self):
        with self.assertRaisesRegex(ValueError, "от 1 до 50"):
            parse_contest_input("Конкурс | 2027-12-20T18:00+00:00 | 0 | Приз")

    def test_contest_card_contains_giveaway_details(self):
        deadline = datetime(2027, 12, 20, 18, 0, tzinfo=timezone.utc)
        card = contest_card("Зимний конкурс", "VIP Gold", deadline, 3, 42, 17)
        self.assertIn("F-RUM GIVEAWAY", card)
        self.assertIn("Зимний конкурс", card)
        self.assertIn("VIP Gold", card)
        self.assertIn("42", card)
        self.assertIn("Конкурс #17", card)

    def test_promo_code_is_normalized(self):
        self.assertEqual(normalize_promo_code("  winter_2026 "), "WINTER_2026")

    def test_promo_code_rejects_invalid_characters(self):
        with self.assertRaises(ValueError):
            normalize_promo_code("bad code!")


if __name__ == "__main__":
    unittest.main()
