"""Tests for per-chat Telegram role hierarchy helpers."""
import unittest

from chat_roles import (
    DEFAULT_COMMAND_PRIORITIES,
    MANAGEABLE_COMMANDS,
    can_manage_priority,
    role_slug,
)


class ChatRoleHelperTests(unittest.TestCase):
    def test_priority_must_be_strictly_higher(self):
        self.assertTrue(can_manage_priority(80, 60))
        self.assertTrue(can_manage_priority(40, 20))
        self.assertFalse(can_manage_priority(60, 60))
        self.assertFalse(can_manage_priority(20, 40))

    def test_default_role_keys_are_stable_and_namespaced(self):
        self.assertEqual(role_slug("Помощник"), role_slug("Помощник"))
        self.assertTrue(role_slug("Helper").startswith("custom_"))
        self.assertNotEqual(role_slug("Helper"), role_slug("Moderator"))

    def test_helper_and_moderator_command_thresholds(self):
        self.assertEqual(DEFAULT_COMMAND_PRIORITIES["warn"], 20)
        self.assertEqual(DEFAULT_COMMAND_PRIORITIES["mute"], 20)
        self.assertEqual(DEFAULT_COMMAND_PRIORITIES["ban"], 40)
        self.assertEqual(DEFAULT_COMMAND_PRIORITIES["purge"], 40)

    def test_sensitive_commands_have_higher_defaults(self):
        self.assertEqual(DEFAULT_COMMAND_PRIORITIES["role"], 80)
        self.assertEqual(DEFAULT_COMMAND_PRIORITIES["blacklist"], 80)
        self.assertIn("editcmd", MANAGEABLE_COMMANDS)
        self.assertIn("reportclose", MANAGEABLE_COMMANDS)


if __name__ == "__main__":
    unittest.main()
