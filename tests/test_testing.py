"""Unit tests for the Telegram private-message test builder."""
import unittest
from unittest.mock import AsyncMock, patch

from testing import AUTO_ASSIGNABLE_ROLE_MAX, AUTO_ASSIGNABLE_ROLE_MIN, _is_test_manager, _parse_fields


class TestBuilderParsingTests(unittest.TestCase):
    def test_pipe_parser_preserves_titles_with_spaces(self):
        self.assertEqual(
            _parse_fields(
                "/createtest Проверка модератора | -100123456789 | moderator | 80 | 7 | 30"
            ),
            ["Проверка модератора", "-100123456789", "moderator", "80", "7", "30"],
        )

    def test_test_auto_assignment_is_limited_to_non_privileged_local_roles(self):
        self.assertEqual(AUTO_ASSIGNABLE_ROLE_MIN, 1)
        self.assertEqual(AUTO_ASSIGNABLE_ROLE_MAX, 79)


class TestManagerPermissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_deputy_and_director_can_manage_tests(self):
        with patch("testing.get_role", new=AsyncMock(return_value="deputy")):
            self.assertTrue(await _is_test_manager(10, 1))
        with patch("testing.get_role", new=AsyncMock(return_value="director")):
            self.assertTrue(await _is_test_manager(11, 1))

    async def test_lower_roles_cannot_manage_tests(self):
        for role in ("chief_curator", "chief_admin", "moderator", "developer", None):
            with self.subTest(role=role):
                with patch("testing.get_role", new=AsyncMock(return_value=role)):
                    self.assertFalse(await _is_test_manager(12, 1))


if __name__ == "__main__":
    unittest.main()
