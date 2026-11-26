import unittest
from types import SimpleNamespace

from moderation import contains_link, owner_summary, registered_chat_count


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

    def test_owner_summary_does_not_expose_secrets(self):
        summary = owner_summary(123456)
        self.assertIn("123456", summary)
        self.assertIn("/warn", summary)
        self.assertNotIn("TOKEN", summary)


if __name__ == "__main__":
    unittest.main()
