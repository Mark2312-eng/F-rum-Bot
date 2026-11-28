"""Detect sudden bursts of new members in connected Telegram groups.

The detector is intentionally alert-only: it never bans or restricts users
automatically, avoiding false positives during legitimate community growth.
"""
from collections import defaultdict, deque
from time import monotonic

from aiogram import Bot
from aiogram.types import Message

from database import database

JOIN_WINDOW_SECONDS = 30
JOIN_BURST_THRESHOLD = 5
ALERT_COOLDOWN_SECONDS = 600
_MAX_TRACKED_CHATS = 2_000

_join_events: dict[int, deque[tuple[float, int]]] = defaultdict(deque)
_last_alert: dict[int, float] = {}


def detect_join_burst(
    chat_id: int,
    member_ids: list[int],
    now: float | None = None,
) -> int | None:
    """Return the distinct join count when a burst is detected.

    Events are held in bounded per-chat deques and stale chats are discarded.
    Repeated IDs in one Telegram service update are counted only once.
    """
    current = monotonic() if now is None else now
    if chat_id not in _join_events and len(_join_events) >= _MAX_TRACKED_CHATS:
        oldest_chat = min(
            _join_events,
            key=lambda key: _join_events[key][-1][0] if _join_events[key] else current,
        )
        _join_events.pop(oldest_chat, None)
        _last_alert.pop(oldest_chat, None)

    events = _join_events[chat_id]
    cutoff = current - JOIN_WINDOW_SECONDS
    while events and events[0][0] < cutoff:
        events.popleft()

    known_ids = {user_id for _timestamp, user_id in events}
    for user_id in member_ids:
        if user_id > 0 and user_id not in known_ids:
            events.append((current, user_id))
            known_ids.add(user_id)

    if len(known_ids) < JOIN_BURST_THRESHOLD:
        return None

    last_alert = _last_alert.get(chat_id)
    if last_alert is not None and current - last_alert < ALERT_COOLDOWN_SECONDS:
        return None

    _last_alert[chat_id] = current
    return len(known_ids)


async def handle_new_members(message: Message, bot: Bot) -> None:
    """Log and announce a join burst for a connected group."""
    if message.chat.type not in {"group", "supergroup"} or not message.new_chat_members:
        return
    if not await database.is_chat_registered(message.chat.id):
        return

    count = detect_join_burst(
        message.chat.id,
        [member.id for member in message.new_chat_members if not member.is_bot],
    )
    if count is None:
        return

    await database.log_moderation_event(
        message.chat.id,
        None,
        None,
        "raid_join_burst",
        f"Обнаружено {count} новых участников за {JOIN_WINDOW_SECONDS} секунд; автоматические санкции не применялись",
    )
    await message.answer(
        "⚠️ <b>Обнаружен всплеск вступлений</b>\n"
        f"За последние {JOIN_WINDOW_SECONDS} секунд присоединились {count} участников.\n"
        "Проверьте список новых аккаунтов и при необходимости включите строгий режим в /settings.\n"
        "Автоматические блокировки не применялись.",
        parse_mode="HTML",
    )
