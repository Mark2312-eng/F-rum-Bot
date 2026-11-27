"""Tests for the canonical staff role catalogue and authorization."""
import unittest
from unittest.mock import AsyncMock, patch

from staff_role_catalog import DEPARTMENT_TITLES, ROLE_CATALOG, STAFF_ROLES
from system_roles import ROLES, can_manage_rank, has_permission, role_key, role_rank


class SystemRoleTests(unittest.IsolatedAsyncioTestCase):
    def test_catalog_contains_every_requested_role_except_implicit_owner(self):
        self.assertEqual(len(STAFF_ROLES), 45)
        self.assertEqual(len(ROLE_CATALOG), len(STAFF_ROLES))
        self.assertEqual(len({role.title for role in STAFF_ROLES}), len(STAFF_ROLES))
        for role in STAFF_ROLES:
            with self.subTest(role=role.key):
                self.assertTrue(role.title)
                self.assertIn(role.department, DEPARTMENT_TITLES)
                self.assertGreater(role.rank, 0)
                self.assertIsInstance(role.permissions, frozenset)

    def test_role_keys_and_title_aliases(self):
        self.assertEqual(role_key("project_team"), "project_team")
        self.assertEqual(role_key("Верховный администратор"), "special_admin")
        self.assertEqual(role_key("Специальный администратор"), "special_admin")
        self.assertEqual(role_key("chief-admin"), "chief_admin")
        self.assertEqual(role_key("Генеральный администратор"), "head_administrator")
        self.assertEqual(role_key("Главный администратор"), "head_administrator")
        self.assertEqual(role_key("Администратор направления"), "administrator")
        self.assertEqual(role_key("Администратор"), "administrator")
        self.assertEqual(role_key("директор_бота"), "director")
        self.assertEqual(role_key("владелец_проекта"), "owner")
        self.assertIsNone(role_key("unknown_role"))

    def test_legacy_assignments_remain_readable(self):
        self.assertIn("director", ROLES)
        self.assertIn("developer", ROLES)
        self.assertEqual(ROLES["developer"]["permissions"], {"staff_view", "technical"})

    def test_role_hierarchy_requires_strictly_higher_rank(self):
        self.assertEqual(role_rank("owner"), 100)
        self.assertEqual(role_rank("project_team"), 95)
        self.assertEqual(role_rank("moderator"), 30)
        self.assertEqual(role_rank("chat_moderator"), 55)
        self.assertEqual(role_rank(None), 0)
        self.assertTrue(can_manage_rank(60, 30))
        self.assertFalse(can_manage_rank(30, 30))
        self.assertFalse(can_manage_rank(30, 60))

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
        with patch("system_roles.database.get_system_role", new=AsyncMock(return_value="tech_specialist")):
            self.assertTrue(await has_permission(300, 100, "technical"))
            self.assertFalse(await has_permission(300, 100, "moderation"))

    async def test_tester_does_not_get_moderation_or_technical_permissions(self):
        with patch("system_roles.database.get_system_role", new=AsyncMock(return_value="tester")):
            self.assertTrue(await has_permission(301, 100, "testing_review"))
            self.assertFalse(await has_permission(301, 100, "moderation"))
            self.assertFalse(await has_permission(301, 100, "technical"))

    async def test_organization_supervisor_is_scoped(self):
        with patch("system_roles.database.get_system_role", new=AsyncMock(return_value="supervisor_umvd")):
            self.assertTrue(await has_permission(302, 100, "organizations"))
            self.assertFalse(await has_permission(302, 100, "moderation"))
            self.assertFalse(await has_permission(302, 100, "staff_manage"))


if __name__ == "__main__":
    unittest.main()
