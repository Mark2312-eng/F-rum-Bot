"""Unit tests for the bot's response formatting."""

import unittest

from main import build_player_message


class BuildPlayerMessageTests(unittest.TestCase):
    def test_escapes_user_supplied_html(self):
        message = build_player_message("<admin>", 42, False)
        self.assertIn("&lt;admin&gt;", message)
        self.assertNotIn("<admin>", message)

    def test_includes_banned_status(self):
        message = build_player_message("Player", 7, True)
        self.assertIn("🔴 Забанен", message)
        self.assertIn("<code>7</code>", message)

    def test_includes_unbanned_status(self):
        message = build_player_message("Player", 8, False)
        self.assertIn("🟢 Не забанен", message)


if __name__ == "__main__":
    unittest.main()
