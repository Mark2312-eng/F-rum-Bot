"""Tests for explicit consent and broadcast subscription controls."""

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from aiogram.types import CallbackQuery, Chat, Message, User

from privacy_broadcast import (
    ConsentGateMiddleware,
    consent_keyboard,
    subscription_keyboard,
)


class ConsentKeyboardTests(unittest.TestCase):
    def test_consent_keyboard_links_and_actions_are_present(self):
        keyboard = consent_keyboard()
        buttons = [button for row in keyboard.inline_keyboard for button in row]
        callbacks = {button.callback_data for button in buttons if button.callback_data}
        urls = {button.url for button in buttons if button.url}
        self.assertIn("consent:accept", callbacks)
        self.assertIn("consent:decline", callbacks)
        self.assertTrue(any(url.endswith("/privacy.html") for url in urls))
        self.assertTrue(any(url.endswith("/personal-data.html") for url in urls))

    def test_subscription_choice_is_separate_from_consent(self):
        keyboard = subscription_keyboard()
        callbacks = {
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
            if button.callback_data
        }
        self.assertEqual(callbacks, {"subscription:yes", "subscription:no"})


class ConsentGateTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def make_message(text):
        return Message(
            message_id=1,
            date=datetime.now(timezone.utc),
            chat=Chat(id=123, type="private"),
            from_user=User(id=456, is_bot=False, first_name="Test"),
            text=text,
        )

    async def test_private_commands_are_blocked_without_consent(self):
        event = self.make_message("/help")
        handler = AsyncMock(return_value="handled")
        middleware = ConsentGateMiddleware()

        with patch("privacy_broadcast.has_consent", new=AsyncMock(return_value=False)):
            with patch("privacy_broadcast.show_consent_prompt", new=AsyncMock()) as prompt:
                result = await middleware(handler, event, {})

        self.assertIsNone(result)
        handler.assert_not_awaited()
        prompt.assert_awaited_once_with(event)

    async def test_start_is_allowed_to_show_the_consent_prompt(self):
        event = self.make_message("/start")
        handler = AsyncMock(return_value="handled")
        middleware = ConsentGateMiddleware()

        with patch("privacy_broadcast.has_consent", new=AsyncMock(return_value=False)) as check:
            result = await middleware(handler, event, {})

        self.assertEqual(result, "handled")
        handler.assert_awaited_once_with(event, {})
        check.assert_not_awaited()

    async def test_private_consent_callback_is_allowed_without_message_text(self):
        message = self.make_message("")
        event = CallbackQuery(
            id="callback-1",
            from_user=message.from_user,
            chat_instance="private-chat",
            message=message,
            data="consent:accept",
        )
        handler = AsyncMock(return_value="handled")
        middleware = ConsentGateMiddleware()

        result = await middleware(handler, event, {})

        self.assertEqual(result, "handled")
        handler.assert_awaited_once_with(event, {})


if __name__ == "__main__":
    unittest.main()
