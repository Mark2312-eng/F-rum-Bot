import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from moderation import contains_link, format_moderation_log, owner_summary
from group_settings import FLOOD_LABELS, LINK_LABELS, settings_keyboard, settings_text


class ModerationUnitTests(unittest.TestCase):
    def test_detects_plain_urls(self):
        message = SimpleNamespace(text="visit https://example.com", caption=None, entities=None, caption_entities=None)
        self.assertTrue(contains_link(message))

    def test_detects_telegram_links(self):
        message = SimpleNamespace(text="join t.me/example", caption=None, entities=None, caption_entities=None)
        self.assertTrue(contains_link(message))

    def test_ignores_plain_text_without_link(self):
        message = SimpleNamespace(text="hello everyone", caption=None, entities=None, caption_entities=None)
        self.assertFalse(contains_link(message))

    def test_owner_summary_uses_persistent_chat_count(self):
        summary = owner_summary(123456, 7)
        self.assertIn("123456", summary)
        self.assertIn("7", summary)
        self.assertIn("кнопки", summary)
        self.assertNotIn("TOKEN", summary)

    def test_moderation_log_formats_events(self):
        from datetime import datetime, timezone
        event = {
            "action": "warning",
            "target_id": 42,
            "actor_id": 7,
            "details": "1/3",
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        }
        rendered = format_moderation_log([event])
        self.assertIn("Предупреждение", rendered)
        self.assertIn("<code>42</code>", rendered)
        self.assertIn("1/3", rendered)

    def test_empty_moderation_log_has_placeholder(self):
        self.assertIn("Событий пока нет", format_moderation_log([]))

    def test_settings_labels_cover_supported_values(self):
        self.assertEqual(set(FLOOD_LABELS), {"off", "balanced", "strict"})
        self.assertEqual(set(LINK_LABELS), {"allow", "block", "mute"})

    def test_settings_text_displays_current_values(self):
        rendered = settings_text({"moderation_mode": "strict", "link_policy": "mute"})
        self.assertIn(FLOOD_LABELS["strict"], rendered)
        self.assertIn(LINK_LABELS["mute"], rendered)

    def test_settings_keyboard_contains_all_options(self):
        keyboard = settings_keyboard("balanced", "block")
        callback_data = {
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        }
        self.assertIn("cfg:flood:strict", callback_data)
        self.assertIn("cfg:links:mute", callback_data)


class PersistentModerationTests(unittest.IsolatedAsyncioTestCase):
    async def test_unregistered_chat_is_not_moderated(self):
        from moderation import moderate_message

        message = SimpleNamespace(
            chat=SimpleNamespace(type="supergroup", id=-100123),
            from_user=SimpleNamespace(id=42, is_bot=False),
            text="https://example.com",
            caption=None,
            entities=None,
            caption_entities=None,
        )
        bot = SimpleNamespace()
        with patch("moderation.database.is_chat_registered", new=AsyncMock(return_value=False)) as registered:
            with patch("moderation.is_chat_admin", new=AsyncMock(return_value=False)) as admin:
                await moderate_message(message, bot, 999)
        registered.assert_awaited_once_with(-100123)
        admin.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
