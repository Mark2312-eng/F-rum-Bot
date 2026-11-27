"""Unit tests for the Telegram private-message test builder."""
import unittest
from unittest.mock import AsyncMock, patch

from testing import (
    AUTO_ASSIGNABLE_ROLE_MAX, AUTO_ASSIGNABLE_ROLE_MIN,
    _can_review_tests, _is_auto_assignable_priority, _is_test_manager, _parse_fields,
)


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
        for priority in (1, 20, 40, 79):
            with self.subTest(priority=priority):
                self.assertTrue(_is_auto_assignable_priority(priority))
        for priority in (0, 80, 99, 100):
            with self.subTest(priority=priority):
                self.assertFalse(_is_auto_assignable_priority(priority))


class TestManagerPermissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_qa_leadership_can_manage_tests(self):
        for role in ("deputy_chief_tester", "qa_head", "project_team", "director", "deputy"):
            with self.subTest(role=role):
                with patch("testing.get_role", new=AsyncMock(return_value=role)):
                    self.assertTrue(await _is_test_manager(10, 1))

    async def test_testers_can_review_but_not_manage_tests(self):
        for role in ("qa_specialist", "senior_tester", "tester", "junior_tester"):
            with self.subTest(role=role):
                with patch("testing.get_role", new=AsyncMock(return_value=role)):
                    self.assertTrue(await _can_review_tests(12, 1))
                    self.assertFalse(await _is_test_manager(12, 1))

    async def test_unrelated_roles_cannot_manage_or_review_tests(self):
        for role in ("chief_tech_specialist", "tech_specialist", "moderator", "developer", None):
            with self.subTest(role=role):
                with patch("testing.get_role", new=AsyncMock(return_value=role)):
                    self.assertFalse(await _is_test_manager(13, 1))
                    self.assertFalse(await _can_review_tests(13, 1))


if __name__ == "__main__":
    unittest.main()
