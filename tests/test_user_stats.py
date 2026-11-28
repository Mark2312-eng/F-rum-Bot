"""Tests for personal Telegram group statistics formatting."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from user_stats import build_user_stats_message


class UserStatsFormattingTests(unittest.TestCase):
    def test_formats_grand_style_profile_and_escapes_user_content(self):
        user = SimpleNamespace(id=123456, full_name="<Member>", username="name&tag")
        stats = {
            "nickname": "<VIP & helper>",
            "first_seen_at": datetime(2026, 11, 18, 12, 7, tzinfo=timezone.utc),
            "join_event_seen": True,
            "invited_by": 987654,
            "warning_count": 2,
            "message_count": 45,
            "today_count": 7,
            "activity_rank": 3,
        }
        text = build_user_stats_message(user, stats, "Модератор", blocked=True)

        self.assertIn("Информация о пользователе", text)
        self.assertIn("Статус: ✨ Модератор", text)
        self.assertIn("Предупреждений: 2/3", text)
        self.assertIn("&lt;VIP &amp; helper&gt;", text)
        self.assertIn("Блокировка чата: 🔒 да", text)
        self.assertIn("Дата вступления в чат: 18.11.2026 12:07", text)
        self.assertIn("Сообщений отправлено: 45", text)
        self.assertIn("Сообщений сегодня: 7", text)
        self.assertIn("Место по активности: №3", text)
        self.assertIn("Пригласил(а): <code>987654</code>", text)
        self.assertIn("name&amp;tag", text)
        self.assertIn("ID: <code>123456</code>", text)

    def test_displays_active_vip_tier_and_expiry(self):
        user = SimpleNamespace(id=77, full_name="VIP User", username="vipuser")
        expiry = datetime(2026, 12, 28, 15, 30, tzinfo=timezone.utc)
        text = build_user_stats_message(
            user,
            {},
            "Пользователь",
            blocked=False,
            vip_membership={"tier": "diamond", "expires_at": expiry},
        )
        self.assertIn("VIP статус: 💎 VIP Diamond до 28.12.2026 15:30", text)

    def test_marks_first_observed_message_and_missing_optional_data(self):
        user = SimpleNamespace(id=42, full_name="User", username=None)
        text = build_user_stats_message(
            user,
            {"first_seen_at": None, "join_event_seen": False},
            "Пользователь",
            blocked=False,
        )
        self.assertIn("Впервые замечен ботом: нет данных", text)
        self.assertIn("VIP статус: нет", text)
        self.assertIn("Пригласил(а): —", text)
        self.assertIn("Username: не указан", text)
        self.assertIn("Сообщений отправлено: 0", text)
        self.assertIn("Блокировка чата: нет", text)


if __name__ == "__main__":
    unittest.main()
