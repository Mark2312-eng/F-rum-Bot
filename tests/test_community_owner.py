import os
import unittest
from unittest.mock import patch

from community_owner import _menu, _owner


class CommunityOwnerControlsTests(unittest.TestCase):
    def test_only_configured_owner_is_authorized(self):
        with patch.dict(os.environ, {"OWNER_TELEGRAM_ID": "12345"}):
            self.assertTrue(_owner(12345))
            self.assertFalse(_owner(12346))
            self.assertFalse(_owner(None))

    def test_invalid_owner_configuration_denies_access(self):
        with patch.dict(os.environ, {"OWNER_TELEGRAM_ID": "not-an-id"}):
            self.assertFalse(_owner(12345))

    def test_owner_menu_contains_contests_and_promos(self):
        keyboard = _menu()
        callbacks = {
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        }
        self.assertIn("owner:community:contests", callbacks)
        self.assertIn("owner:community:promos", callbacks)
        self.assertIn("owner:community:createcontest", callbacks)
        self.assertIn("owner:community:createpromo", callbacks)


if __name__ == "__main__":
    unittest.main()
