import unittest

from vip_admin import parse_grant_input


class VipAdminInputTests(unittest.TestCase):
    def test_valid_grant_input(self):
        self.assertEqual(parse_grant_input("123456789 gold 30"), (123456789, "gold", 30))

    def test_tier_is_case_insensitive(self):
        self.assertEqual(parse_grant_input("123456789 DIAMOND 7"), (123456789, "diamond", 7))

    def test_rejects_invalid_tier_and_duration(self):
        self.assertIsNone(parse_grant_input("123456789 platinum 30"))
        self.assertIsNone(parse_grant_input("123456789 silver 0"))
        self.assertIsNone(parse_grant_input("123456789 silver 3651"))

    def test_rejects_malformed_and_non_numeric_ids(self):
        self.assertIsNone(parse_grant_input("abc silver 30"))
        self.assertIsNone(parse_grant_input("123456789 silver"))
        self.assertIsNone(parse_grant_input("123456789 silver 30 extra"))


if __name__ == "__main__":
    unittest.main()
