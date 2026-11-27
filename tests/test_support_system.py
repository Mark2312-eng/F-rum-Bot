import hashlib
import hmac
import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from support_system import STAFF_APPLICATION_ROLES, _make_user_session, _session_user, _valid_telegram_login


class TelegramLoginTests(unittest.TestCase):
    def setUp(self):
        self.token = "123456:unit-test-token"
        self.env = patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": self.token,
            "PANEL_SESSION_SECRET": "test-secret-that-is-long-enough-for-cookie-signing",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def signed_payload(self, **extra):
        data = {
            "id": "123456789",
            "first_name": "Test",
            "username": "test_user",
            "auth_date": str(int(time.time())),
            **extra,
        }
        data_check = "\n".join(
            f"{key}={str(data[key]).lower() if isinstance(data[key], bool) else data[key]}"
            for key in sorted(data)
        )
        secret = hashlib.sha256(self.token.encode()).digest()
        data["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        return data

    def test_valid_login_payload(self):
        self.assertTrue(_valid_telegram_login(self.signed_payload()))

    def test_expired_login_payload_is_rejected(self):
        self.assertFalse(_valid_telegram_login(self.signed_payload(auth_date=str(int(time.time()) - 601))))

    def test_tampered_login_payload_is_rejected(self):
        data = self.signed_payload()
        data["username"] = "other_user"
        self.assertFalse(_valid_telegram_login(data))

    def test_boolean_login_claim_is_canonicalized(self):
        self.assertTrue(_valid_telegram_login(self.signed_payload(allows_write_to_pm=True)))

    def test_signed_user_session_round_trip(self):
        token = _make_user_session(987654321)
        request = SimpleNamespace(cookies={"support_session": token})
        self.assertEqual(_session_user(request), 987654321)

    def test_staff_application_roles_are_limited_to_non_privileged_roles(self):
        self.assertEqual(STAFF_APPLICATION_ROLES, {"helper", "moderator", "support"})

    def test_invalid_user_session_is_rejected(self):
        request = SimpleNamespace(cookies={"support_session": "987654321.9999999999.invalid"})
        self.assertIsNone(_session_user(request))


if __name__ == "__main__":
    unittest.main()
