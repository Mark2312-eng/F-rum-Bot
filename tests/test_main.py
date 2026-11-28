"""Tests for configuration, XenForo API calls, and response formatting."""

import unittest
from unittest.mock import AsyncMock, MagicMock

import aiohttp
from aiohttp import web

from moderation import (
    _flood_notice_times,
    _message_times,
    cleanup_flood_state,
    should_notify_flood,
)

from main import (
    acquire_telegram_polling_lock,
    POLLING_ADVISORY_LOCK_ID,
    _panel_require_owner,
    panel_people,
    panel_member_history,
    build_main_keyboard,
    build_owner_keyboard,
    build_section_keyboard,
    build_player_message,
    build_profile_message,
    build_stats_message,
    find_forum_user,
    fetch_forum_stats,
    format_forum_date,
    get_forum_url,
    get_port,
    PENDING_INPUTS,
    has_pending_input,
    pop_pending_input,
    set_pending_input,
)


class ConfigurationTests(unittest.TestCase):
    def test_port_default_and_valid_value(self):
        self.assertEqual(get_port("10000"), 10000)

    def test_rejects_invalid_port(self):
        for value in ("abc", "0", "65536", "-1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                get_port(value)

    def test_forum_url_preserves_installation_path(self):
        self.assertEqual(
            get_forum_url("https://forum.example/community"),
            "https://forum.example/community/",
        )

    def test_rejects_invalid_forum_url(self):
        values = (
            "",
            "forum.example",
            "ftp://forum.example",
            "https://user:pass@forum.example",
            "https://forum.example:invalid",
        )
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                get_forum_url(value)

    def test_profile_link_uses_forum_installation_path(self):
        message = build_player_message(
            "Player", 10, False, "https://forum.example/community/"
        )
        self.assertIn(
            "https://forum.example/community/index.php?members/10/",
            message,
        )


class ProfileFormattingTests(unittest.TestCase):
    def test_profile_message_contains_available_fields_and_escapes_html(self):
        message = build_profile_message(
            "<Admin>",
            42,
            {
                "username": "<Admin>",
                "user_title": "VIP & helper",
                "message_count": 120,
                "trophy_points": 15,
                "is_banned": False,
            },
            "https://forum.example/",
        )
        self.assertIn("&lt;Admin&gt;", message)
        self.assertIn("VIP &amp; helper", message)
        self.assertIn("Сообщений:", message)
        self.assertIn("Очки достижений:", message)
        self.assertIn("🟢 Не забанен", message)

    def test_profile_message_handles_missing_optional_fields(self):
        message = build_profile_message(
            "Player", 7, {"is_banned": True}, "https://forum.example/"
        )
        self.assertIn("ID: <code>7</code>", message)
        self.assertIn("🔴 Забанен", message)
        self.assertNotIn("Регистрация:", message)

    def test_format_forum_date_rejects_invalid_values(self):
        self.assertIsNone(format_forum_date(None))
        self.assertIsNone(format_forum_date("not-a-date"))
        self.assertIsNone(format_forum_date(True))

    def test_stats_message_formats_totals_and_escapes_latest_username(self):
        message = build_stats_message(
            {
                "totals": {"threads": 1234, "messages": 5678, "users": 90},
                "online": {"total": 12, "members": 7, "guests": 5},
                "latest_user": {"username": "<NewUser>"},
            },
            "https://forum.example/",
        )
        self.assertIn("1 234", message)
        self.assertIn("5 678", message)
        self.assertIn("👥 Пользователей: <b>90</b>", message)
        self.assertIn("Сейчас онлайн", message)
        self.assertIn("&lt;NewUser&gt;", message)

    def test_stats_message_handles_missing_metrics(self):
        self.assertIn(
            "не вернул доступные",
            build_stats_message({}, "https://forum.example/"),
        )

    def test_moderation_menu_contains_core_actions(self):
        keyboard = build_section_keyboard()
        callbacks = {
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
            if button.callback_data
        }
        self.assertIn("owner:warn", callbacks)
        self.assertIn("owner:mute", callbacks)
        self.assertIn("owner:settings", callbacks)
        self.assertIn("owner:modlog", callbacks)
        self.assertIn("menu:home", callbacks)

    def test_owner_keyboard_exposes_vip_shop(self):
        callbacks = {
            button.callback_data
            for row in build_owner_keyboard().inline_keyboard
            for button in row
            if button.callback_data
        }
        self.assertIn("owner:vip", callbacks)

    def test_main_keyboard_is_moderation_first_and_owner_panel_is_private(self):
        public_keyboard = build_main_keyboard("https://forum.example/")
        public_callbacks = {
            button.callback_data
            for row in public_keyboard.inline_keyboard
            for button in row
            if button.callback_data
        }
        self.assertIn("menu:profile", public_callbacks)
        self.assertIn("menu:punish", public_callbacks)
        self.assertIn("menu:stats", public_callbacks)
        self.assertNotIn("owner_panel", public_callbacks)
        self.assertFalse(any(button.web_app for row in public_keyboard.inline_keyboard for button in row))

        owner_keyboard = build_main_keyboard("https://forum.example/", is_owner=True)
        owner_callbacks = {
            button.callback_data
            for row in owner_keyboard.inline_keyboard
            for button in row
            if button.callback_data
        }
        self.assertIn("owner_panel", owner_callbacks)



class PendingInputSecurityTests(unittest.TestCase):
    def setUp(self):
        PENDING_INPUTS.clear()

    def tearDown(self):
        PENDING_INPUTS.clear()

    def test_pending_input_is_scoped_to_chat_and_user_and_consumed_once(self):
        set_pending_input(-1001, 42, "profile")

        self.assertTrue(has_pending_input(-1001, 42))
        self.assertFalse(has_pending_input(-1002, 42))
        self.assertIsNone(pop_pending_input(-1002, 42))
        self.assertEqual(pop_pending_input(-1001, 42), "profile")
        self.assertIsNone(pop_pending_input(-1001, 42))

    def test_expired_pending_input_is_rejected(self):
        from unittest.mock import patch

        with patch("main.time.monotonic", return_value=100.0):
            set_pending_input(-1001, 42, "mod_warn")
        with patch("main.time.monotonic", return_value=401.0):
            self.assertFalse(has_pending_input(-1001, 42))
            self.assertIsNone(pop_pending_input(-1001, 42))



class FloodProtectionTests(unittest.TestCase):
    def setUp(self):
        _message_times.clear()
        _flood_notice_times.clear()
        import moderation
        moderation._last_flood_sweep = 0.0

    def tearDown(self):
        _message_times.clear()
        _flood_notice_times.clear()

    def test_flood_notices_are_throttled_per_chat_and_user(self):
        key = (-1001, 42)
        self.assertTrue(should_notify_flood(key, 100.0))
        self.assertFalse(should_notify_flood(key, 110.0))
        self.assertTrue(should_notify_flood(key, 131.0))
        self.assertTrue(should_notify_flood((-1002, 42), 131.0))

    def test_flood_state_cleanup_removes_inactive_users(self):
        import moderation
        _message_times[(-1001, 42)].extend([1.0, 2.0])
        _message_times[(-1002, 43)].append(99.0)
        _flood_notice_times[(-1001, 42)] = 1.0
        moderation._last_flood_sweep = 1.0

        cleanup_flood_state(100.0)

        self.assertNotIn((-1001, 42), _message_times)
        self.assertIn((-1002, 43), _message_times)
        self.assertNotIn((-1001, 42), _flood_notice_times)


class XenForoApiTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def make_response(status, payload=None, error=None):
        response = MagicMock()
        response.status = status
        response.json = AsyncMock(return_value=payload)
        response.raise_for_status = MagicMock(side_effect=error)
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=False)
        return response

    async def test_stats_request_rejects_html_challenge_and_logs_safe_metadata(self):
        response = self.make_response(200, {"ignored": True})
        response.headers = {"Content-Type": "text/html; charset=utf-8", "Server": "anti-ddos"}
        response.url = __import__("yarl").URL("https://forum.example/api/stats/")
        session = MagicMock()
        session.get.return_value = response

        with self.assertRaisesRegex(ValueError, "non-JSON"):
            await fetch_forum_stats(session, "https://forum.example/", "secret-test-key")

        self.assertEqual(
            session.get.call_args.kwargs["headers"]["Accept"],
            "application/json",
        )

    async def test_lookup_and_profile_requests_use_key_and_expected_urls(self):
        session = MagicMock()
        lookup_response = self.make_response(
            200, {"user": {"user_id": 23}}
        )
        profile_response = self.make_response(
            200, {"user": {"is_banned": True}}
        )
        session.get.side_effect = [lookup_response, profile_response]

        result = await find_forum_user(
            session,
            "https://forum.example/community/",
            "Test User",
            "test-key",
        )

        self.assertEqual(result, (23, {"is_banned": True}))
        first_call = session.get.call_args_list[0]
        self.assertEqual(
            first_call.args[0],
            "https://forum.example/community/api/users/find-name",
        )
        self.assertEqual(first_call.kwargs["params"], {"username": "Test User"})
        self.assertEqual(first_call.kwargs["headers"]["XF-Api-Key"], "test-key")
        self.assertEqual(
            session.get.call_args_list[1].args[0],
            "https://forum.example/community/api/users/23",
        )

    async def test_lookup_404_returns_not_found(self):
        session = MagicMock()
        session.get.return_value = self.make_response(404)

        self.assertEqual(
            await find_forum_user(
                session, "https://forum.example/", "missing", "key"
            ),
            (None, None),
        )

    async def test_profile_404_returns_not_found(self):
        session = MagicMock()
        session.get.side_effect = [
            self.make_response(200, {"user": {"user_id": 12}}),
            self.make_response(404),
        ]

        self.assertEqual(
            await find_forum_user(
                session, "https://forum.example/", "missing", "key"
            ),
            (None, None),
        )

    async def test_http_errors_are_propagated_for_handler_to_report(self):
        session = MagicMock()
        error = aiohttp.ClientResponseError(
            request_info=MagicMock(), history=(), status=403
        )
        session.get.return_value = self.make_response(403, error=error)

        with self.assertRaises(aiohttp.ClientResponseError):
            await find_forum_user(
                session, "https://forum.example/", "private", "key"
            )


class PollingLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_lock_uses_dedicated_postgres_connection(self):
        import os
        from unittest.mock import patch

        connection = MagicMock()
        connection.fetchval = AsyncMock(return_value=True)
        connection.close = AsyncMock()
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://example/test"}), \
             patch("main.asyncpg.connect", new_callable=AsyncMock, return_value=connection) as connect:
            acquired = await acquire_telegram_polling_lock()

        self.assertIs(acquired, connection)
        connect.assert_awaited_once_with(
            dsn="postgresql://example/test", ssl="require", timeout=10, command_timeout=10
        )
        connection.fetchval.assert_awaited_once_with(
            "SELECT pg_try_advisory_lock($1)", POLLING_ADVISORY_LOCK_ID
        )
        connection.close.assert_not_awaited()


class PanelRoleAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_role_management_requires_exact_panel_origin(self):
        from unittest.mock import patch

        request = MagicMock()
        request.headers = {"Origin": "https://evil.example"}
        with patch.dict("os.environ", {"PANEL_ORIGIN": "https://f-rum-bot-panel.onrender.com", "OWNER_TELEGRAM_ID": "123"}), \
             patch("main._panel_user", return_value=123):
            with self.assertRaises(web.HTTPForbidden):
                await _panel_require_owner(request)

    async def test_role_management_rejects_non_owner(self):
        from unittest.mock import patch

        request = MagicMock()
        request.headers = {"Origin": "https://f-rum-bot-panel.onrender.com"}
        with patch.dict("os.environ", {"PANEL_ORIGIN": "https://f-rum-bot-panel.onrender.com", "OWNER_TELEGRAM_ID": "123"}), \
             patch("main._panel_user", return_value=456):
            with self.assertRaises(web.HTTPForbidden):
                await _panel_require_owner(request)

    async def test_people_endpoint_requires_owner(self):
        from unittest.mock import patch

        request = MagicMock()
        with patch("main._panel_require_owner", new=AsyncMock(side_effect=web.HTTPForbidden())) as require_owner:
            with self.assertRaises(web.HTTPForbidden):
                await panel_people(request)
        require_owner.assert_awaited_once_with(request)


    async def test_member_history_requires_owner_before_database_access(self):
        from unittest.mock import patch

        request = MagicMock()
        with patch("main._panel_require_owner", new=AsyncMock(side_effect=web.HTTPForbidden())) as require_owner:
            with patch("main.database._require_pool") as get_pool:
                with self.assertRaises(web.HTTPForbidden):
                    await panel_member_history(request)
        require_owner.assert_awaited_once_with(request)
        get_pool.assert_not_called()

    async def test_member_history_returns_profile_and_targeted_audit_events(self):
        from datetime import datetime, timezone
        from unittest.mock import patch

        created_at = datetime.now(timezone.utc)
        member = {
            "chat_id": -1001, "chat_title": "Test group", "user_id": 42,
            "username": "member", "display_name": "Member", "message_count": 17,
            "warning_count": 2, "role_title": "Участник", "priority": 0,
            "first_seen_at": created_at,
        }
        event = {"actor_id": 7, "action": "warn", "details": "Правила группы",
                 "created_at": created_at, "category": "moderation"}
        pool = MagicMock()
        pool.fetchrow = AsyncMock(return_value=member)
        pool.fetch = AsyncMock(return_value=[event])
        request = MagicMock()
        request.match_info = {"chat_id": "-1001", "user_id": "42"}
        request.query = {}

        with patch("main._panel_require_owner", new=AsyncMock(return_value=123)):
            with patch("main.database.is_chat_registered", new=AsyncMock(return_value=True)):
                with patch("main.database._require_pool", return_value=pool):
                    response = await panel_member_history(request)

        payload = __import__("json").loads(response.body)
        self.assertEqual(payload["member"]["user_id"], 42)
        self.assertEqual(payload["member"]["warning_count"], 2)
        self.assertEqual(payload["events"][0]["action"], "warn")
        self.assertEqual(payload["events"][0]["actor_id"], 7)
        self.assertEqual(payload["events"][0]["category"], "moderation")
        pool.fetch.assert_awaited_once()
        self.assertIn("UNION ALL", pool.fetch.await_args.args[0])
        self.assertIn("chat_role_audit", pool.fetch.await_args.args[0])


    async def test_member_history_rejects_unknown_event_category(self):
        from unittest.mock import patch

        request = MagicMock()
        request.match_info = {"chat_id": "-1001", "user_id": "42"}
        request.query = {"category": "other"}
        with patch("main._panel_require_owner", new=AsyncMock(return_value=123)):
            with patch("main.database.is_chat_registered", new=AsyncMock(return_value=True)):
                with patch("main.database._require_pool") as get_pool:
                    with self.assertRaises(web.HTTPBadRequest):
                        await panel_member_history(request)
        get_pool.assert_not_called()

    async def test_member_history_rejects_invalid_actor_filter(self):
        from unittest.mock import patch

        request = MagicMock()
        request.match_info = {"chat_id": "-1001", "user_id": "42"}
        request.query = {"actor_id": "not-an-id"}
        with patch("main._panel_require_owner", new=AsyncMock(return_value=123)):
            with patch("main.database.is_chat_registered", new=AsyncMock(return_value=True)):
                with patch("main.database._require_pool") as get_pool:
                    with self.assertRaises(web.HTTPBadRequest):
                        await panel_member_history(request)
        get_pool.assert_not_called()




if __name__ == "__main__":
    unittest.main()
