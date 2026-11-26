import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from moderation import contains_link, owner_summary


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
        self.assertIn("/warn", summary)
        self.assertNotIn("TOKEN", summary)


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
