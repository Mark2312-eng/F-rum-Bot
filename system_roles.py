"""Global system staff roles and role-aware command authorization."""
from html import escape

from aiogram.types import Message

from database import database

# Higher numbers mean greater authority. Technical/support roles are deliberately
# separate from the moderation chain and do not inherit moderation permissions.
ROLES = {
    "director": {"title": "Директор бота", "rank": 90, "permissions": {"staff_manage", "staff_view", "moderation", "reports", "settings", "technical", "support"}},
    "deputy": {"title": "Заместитель директора", "rank": 80, "permissions": {"staff_manage", "staff_view", "moderation", "reports", "settings", "support"}},
    "chief_curator": {"title": "Главный куратор", "rank": 70, "permissions": {"staff_view", "moderation", "reports", "settings"}},
    "curator": {"title": "Куратор", "rank": 60, "permissions": {"staff_view", "moderation", "reports"}},
    "chief_admin": {"title": "Главный администратор", "rank": 55, "permissions": {"staff_view", "moderation", "reports", "settings"}},
    "admin": {"title": "Администратор", "rank": 50, "permissions": {"moderation", "reports"}},
    "developer": {"title": "Разработчик", "rank": 45, "permissions": {"staff_view", "technical"}},
    "senior_mod": {"title": "Старший модератор", "rank": 40, "permissions": {"moderation", "reports"}},
    "tech_admin": {"title": "Технический администратор", "rank": 38, "permissions": {"technical"}},
    "moderator": {"title": "Модератор", "rank": 30, "permissions": {"moderation", "reports"}},
    "support_lead": {"title": "Главный специалист поддержки", "rank": 25, "permissions": {"support", "reports"}},
    "junior_mod": {"title": "Младший модератор", "rank": 20, "permissions": {"moderation", "reports"}},
    "support": {"title": "Специалист поддержки", "rank": 15, "permissions": {"support"}},
    "trainee": {"title": "Стажёр", "rank": 10, "permissions": {"reports"}},
}

ALIASES = {key: key for key in ROLES}
ALIASES.update({item["title"].lower().replace(" ", "_"): key for key, item in ROLES.items()})


def role_key(value: str) -> str | None:
    key = value.strip().lower().replace("-", "_")
    return ALIASES.get(key)


async def get_role(user_id: int, owner_id: int) -> str | None:
    if user_id == owner_id and owner_id > 0:
        return "owner"
    return await database.get_system_role(user_id)


async def has_permission(user_id: int, owner_id: int, permission: str) -> bool:
    role = await get_role(user_id, owner_id)
    if role == "owner":
        return True
    return bool(role in ROLES and permission in ROLES[role]["permissions"])


async def _actor_rank(user_id: int, owner_id: int) -> int:
    role = await get_role(user_id, owner_id)
    return 100 if role == "owner" else ROLES.get(role, {}).get("rank", 0)


def _role_label(key: str | None) -> str:
    if key == "owner":
        return "Владелец бота"
    return ROLES.get(key or "", {}).get("title", "Без должности")


async def _deny(message: Message) -> None:
    await message.answer("⛔ Недостаточно полномочий для этой команды.")


async def staff_command(message: Message, owner_id: int) -> None:
    if not message.from_user or not await has_permission(message.from_user.id, owner_id, "staff_view"):
        await _deny(message)
        return
    rows = await database.list_system_staff()
    lines = ["👥 <b>Команда F-rum-Bot</b>", f"👑 Владелец: <code>{owner_id}</code>"]
    if rows:
        for row in rows:
            lines.append(f"• <b>{escape(_role_label(row['role_key']))}</b> — <code>{row['user_id']}</code>")
    else:
        lines.append("Системные должности пока не назначены.")
    await message.answer("\n".join(lines), parse_mode="HTML")


async def myrole_command(message: Message, owner_id: int) -> None:
    if not message.from_user:
        return
    role = await get_role(message.from_user.id, owner_id)
    await message.answer(f"Ваша системная должность: <b>{escape(_role_label(role))}</b>.", parse_mode="HTML")


async def staffinfo_command(message: Message, owner_id: int) -> None:
    if not message.from_user or not await has_permission(message.from_user.id, owner_id, "staff_view"):
        await _deny(message)
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.reply("Формат: /staffinfo TELEGRAM_ID")
        return
    target_id = int(parts[1])
    role = await get_role(target_id, owner_id)
    await message.answer(
        f"👤 <b>Карточка сотрудника</b>\nID: <code>{target_id}</code>\nДолжность: <b>{escape(_role_label(role))}</b>",
        parse_mode="HTML",
    )


async def setrole_command(message: Message, owner_id: int, forced_role: str | None = None) -> None:
    if not message.from_user:
        return
    actor_id = message.from_user.id
    if not await has_permission(actor_id, owner_id, "staff_manage"):
        await _deny(message)
        return
    parts = (message.text or "").split()
    if forced_role:
        if len(parts) != 2:
            await message.reply(f"Формат: /{forced_role} TELEGRAM_ID")
            return
        target_raw, requested_role = parts[1], forced_role
    else:
        if len(parts) != 3:
            await message.reply("Формат: /setrole TELEGRAM_ID должность\nДоступные ключи: " + ", ".join(ROLES))
            return
        target_raw, requested_role = parts[1], parts[2]
    if not target_raw.isdigit():
        await message.reply("Telegram ID должен быть числом.")
        return
    target_id = int(target_raw)
    key = role_key(requested_role)
    if not key:
        await message.reply("Неизвестная должность. Доступные ключи: " + ", ".join(ROLES))
        return
    if target_id == owner_id or target_id == actor_id:
        await message.reply("Нельзя изменить должность владельца или самого себя.")
        return
    actor_rank = await _actor_rank(actor_id, owner_id)
    current_role = await get_role(target_id, owner_id)
    current_rank = await _actor_rank(target_id, owner_id)
    if actor_rank <= max(current_rank, ROLES[key]["rank"]):
        await message.reply("⛔ Нельзя назначать равную/старшую должность или менять сотрудника равного/старшего уровня.")
        return
    await database.set_system_role(target_id, key, actor_id)
    await database.add_system_staff_log(actor_id, target_id, "set_role", key)
    await message.answer(f"✅ Пользователю <code>{target_id}</code> назначена должность: <b>{escape(ROLES[key]['title'])}</b>.", parse_mode="HTML")


async def staffremove_command(message: Message, owner_id: int) -> None:
    if not message.from_user or not await has_permission(message.from_user.id, owner_id, "staff_manage"):
        await _deny(message)
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.reply("Формат: /staffremove TELEGRAM_ID")
        return
    target_id = int(parts[1])
    if target_id in {owner_id, message.from_user.id}:
        await message.reply("Нельзя снять должность владельца или самого себя.")
        return
    actor_rank = await _actor_rank(message.from_user.id, owner_id)
    target_rank = await _actor_rank(target_id, owner_id)
    if actor_rank <= target_rank:
        await message.reply("Нельзя снимать сотрудника равного или более высокого уровня.")
        return
    removed = await database.remove_system_role(target_id)
    if removed:
        await database.add_system_staff_log(message.from_user.id, target_id, "remove_role", "")
    await message.answer("✅ Должность снята." if removed else "Сотрудник не найден.")


async def stafflog_command(message: Message, owner_id: int) -> None:
    if not message.from_user or not await has_permission(message.from_user.id, owner_id, "staff_view"):
        await _deny(message)
        return
    rows = await database.get_system_staff_log(15)
    if not rows:
        await message.answer("📋 Журнал назначений пока пуст.")
        return
    lines = ["📋 <b>Журнал системной команды</b>"]
    for row in rows:
        lines.append(
            f"• <code>{row['actor_id']}</code> → <code>{row['target_id']}</code>: "
            f"{escape(row['action'])} {escape(row['details'] or '')}"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")


async def syshealth_command(message: Message, owner_id: int) -> None:
    if not message.from_user or not await has_permission(message.from_user.id, owner_id, "technical"):
        await _deny(message)
        return
    try:
        pool = database._require_pool()
        value = await pool.fetchval("SELECT 1")
        db_status = "🟢 PostgreSQL доступен" if value == 1 else "🟡 Неожиданный ответ БД"
    except Exception:
        db_status = "🔴 PostgreSQL недоступен"
    import os
    await message.answer(
        "🛠 <b>Техническая диагностика F-rum-Bot</b>\\n"
        f"{db_status}\\n"
        "Токен Telegram: " + ("настроен" if os.getenv("TELEGRAM_BOT_TOKEN") else "не настроен") + "\\n"
        "XenForo API: " + ("настроен" if os.getenv("XF_API_KEY") else "не настроен"),
        parse_mode="HTML",
    )


async def rolehelp_command(message: Message, owner_id: int) -> None:
    role = await get_role(message.from_user.id, owner_id) if message.from_user else None
    permissions = set() if role not in ROLES else ROLES[role]["permissions"]
    lines = [f"🧭 <b>Должность:</b> {escape(_role_label(role))}", "", "<b>Доступные команды</b>",
             "/myrole — моя должность", "/rolehelp — справка"]
    if role == "owner" or "staff_view" in permissions:
        lines.extend(["/staff — состав команды", "/staffinfo ID — карточка сотрудника", "/stafflog — журнал назначений"])
    if role == "owner" or "staff_manage" in permissions:
        lines.extend(["/setrole ID КЛЮЧ — назначить должность", "/staffremove ID — снять должность",
                      "", "<b>Ключи должностей:</b>"] + [f"{key} — {data['title']}" for key, data in ROLES.items()])
    if role == "owner" or "moderation" in permissions:
        lines.extend(["", "<b>Модерация:</b> /warn, /warns, /clearwarns, /mute, /unmute, /ban, /unban, /kick, /purge, /modstats, /modlog, /nick"])
    if role == "owner" or "reports" in permissions:
        lines.extend(["", "<b>Жалобы:</b> /reports, /reportclose"])
    if role == "owner" or "settings" in permissions:
        lines.extend(["", "<b>Настройки:</b> /settings"])
    if role == "owner" or "technical" in permissions:
        lines.extend(["", "<b>Техника:</b> /syshealth"])
    if role == "owner" or "support" in permissions:
        lines.extend(["", "<b>Поддержка:</b> /reporthelp"])
    await message.answer("\\n".join(lines), parse_mode="HTML")


async def reporthelp_command(message: Message, owner_id: int) -> None:
    if not message.from_user or not await has_permission(message.from_user.id, owner_id, "support"):
        await _deny(message)
        return
    await message.answer(
        "🎧 <b>Регламент поддержки</b>\\n"
        "1. Уточните проблему и Telegram ID пользователя.\\n"
        "2. Не запрашивайте пароли, коды входа или токены.\\n"
        "3. Для нарушений используйте /report в подключённой группе.\\n"
        "4. Передайте техническую неисправность разработчику.",
        parse_mode="HTML",
    )
