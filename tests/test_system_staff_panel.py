"""Owner-only API tests for global staff management."""
import json
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import web

from main import panel_system_staff, panel_assign_system_staff, panel_remove_system_staff


class SystemStaffPanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_staff_catalog_is_returned_to_owner(self):
        request = MagicMock()
        row = {"user_id": 22, "role_key": "tester", "assigned_by": 11, "assigned_at": datetime(2026, 1, 1)}
        with patch("main._panel_require_owner", new=AsyncMock(return_value=11)):
            with patch("main.database.list_system_staff", new=AsyncMock(return_value=[row])):
                with patch("main.database.get_system_staff_log", new=AsyncMock(return_value=[])):
                    response = await panel_system_staff(request)
        payload = json.loads(response.text)
        self.assertTrue(any(role["key"] == "tester" for role in payload["roles"]))
        self.assertEqual(payload["staff"][0]["user_id"], 22)

    async def test_assignment_rejects_unknown_role_before_database(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={"user_id": 22, "role_key": "not_a_role"})
        with patch("main._panel_require_owner", new=AsyncMock(return_value=11)):
            with patch.dict("os.environ", {"OWNER_TELEGRAM_ID": "11"}):
                with patch("main.database.assign_system_role_guarded", new=AsyncMock()) as assign:
                    with self.assertRaises(web.HTTPBadRequest):
                        await panel_assign_system_staff(request)
        assign.assert_not_awaited()

    async def test_assignment_uses_guarded_database_method(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={"user_id": 22, "role_key": "tester"})
        with patch("main._panel_require_owner", new=AsyncMock(return_value=11)):
            with patch.dict("os.environ", {"OWNER_TELEGRAM_ID": "11"}):
                with patch("main.database.assign_system_role_guarded", new=AsyncMock(return_value=True)) as assign:
                    response = await panel_assign_system_staff(request)
        self.assertEqual(json.loads(response.text)["role_key"], "tester")
        assign.assert_awaited_once()

    async def test_removal_rejects_owner_target(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={"user_id": 11})
        with patch("main._panel_require_owner", new=AsyncMock(return_value=11)):
            with patch.dict("os.environ", {"OWNER_TELEGRAM_ID": "11"}):
                with patch("main.database.remove_system_role_guarded", new=AsyncMock()) as remove:
                    with self.assertRaises(web.HTTPBadRequest):
                        await panel_remove_system_staff(request)
        remove.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
