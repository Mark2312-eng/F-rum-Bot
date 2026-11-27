"""Tests for global staff-role definitions and authorization."""
import unittest
from unittest.mock import AsyncMock, patch

from system_roles import ROLES, has_permission, role_key


class SystemRoleTests(unittest.IsolatedAsyncioTestCase):
    def test_all_staff_roles_have_titles_ranks_and_permissions(self):
        self.assertGreaterEqual(len(ROLES), 10)
        for key, role in ROLES.items():
            with self.subTest(role=key):
                self.assertTrue(role["title"])
                self.assertGreater(role["rank"], 0)
                self.assertIsInstance(role["permissions"], set)

    def test_role_keys_and_title_aliases(self):
        self.assertEqual(role_key("director"), "director")
        self.assertEqual(role_key("chief-admin"), "chief_admin")
        self.assertEqual(role_key("директор_бота"), "director")
        self.assertIsNone(role_key("unknown_role"))

    async def test_owner_has_all_permissions(self):
        self.assertTrue(await has_permission(100, 100, "technical"))
        self.assertTrue(await has_permission(100, 100, "staff_manage"))

    async def test_moderator_does_not_get_staff_management_or_settings(self):
        with patch("system_roles.database.get_system_role", new=AsyncMock(return_value="moderator")):
            self.assertTrue(await has_permission(200, 100, "moderation"))
            self.assertTrue(await has_permission(200, 100, "reports"))
            self.assertFalse(await has_permission(200, 100, "staff_manage"))
            self.assertFalse(await has_permission(200, 100, "settings"))

    async def test_technical_role_does_not_get_moderation(self):
        with patch("system_roles.database.get_system_role", new=AsyncMock(return_value="developer")):
            self.assertTrue(await has_permission(300, 100, "technical"))
            self.assertFalse(await has_permission(300, 100, "moderation"))


if __name__ == "__main__":
    unittest.main()
