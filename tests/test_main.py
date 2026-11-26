"""Tests for configuration, XenForo API calls, and response formatting."""

import unittest
from unittest.mock import AsyncMock, MagicMock

import aiohttp

from main import (
    build_main_keyboard,
    build_player_message,
    build_profile_message,
    build_stats_message,
    find_forum_user,
    fetch_forum_stats,
    format_forum_date,
    get_forum_url,
    get_port,
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

    def test_main_keyboard_shows_button_sections_and_owner_only_panel(self):
        public_keyboard = build_main_keyboard("https://forum.example/")
        public_callbacks = {
            button.callback_data
            for row in public_keyboard.inline_keyboard
            for button in row
            if button.callback_data
        }
        self.assertIn("menu:game", public_callbacks)
        self.assertIn("menu:economy", public_callbacks)
        self.assertNotIn("owner_panel", public_callbacks)

        owner_keyboard = build_main_keyboard("https://forum.example/", is_owner=True)
        owner_callbacks = {
            button.callback_data
            for row in owner_keyboard.inline_keyboard
            for button in row
            if button.callback_data
        }
        self.assertIn("owner_panel", owner_callbacks)



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


if __name__ == "__main__":
    unittest.main()
