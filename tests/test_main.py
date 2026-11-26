"""Tests for configuration, XenForo API calls, and response formatting."""

import unittest
from unittest.mock import AsyncMock, MagicMock

import aiohttp

from main import build_player_message, find_forum_user, get_forum_url, get_port


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
