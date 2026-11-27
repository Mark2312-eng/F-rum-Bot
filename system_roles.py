"""Global system staff roles and role-aware command authorization."""
from html import escape

from aiogram.types import Message

from database import database
from staff_role_catalog import DEPARTMENT_TITLES, ROLE_CATALOG

# Role ranks are used only for safe assignment ordering. Department permissions
# remain separate: technical, QA, support and organization roles do not inherit
# moderation or global administration access.
ROLES = {
    key: {"title": role.title, "rank": role.rank, "permissions": set(role.permissions)}
    for key, role in ROLE_CATALOG.items()
}

# Compatibility keys retained for existing database assignments.
LEGACY_ROLES = {
    "director": {"title": "Директор бота", "rank": 90, "permissions": {"staff_manage", "staff_view", "moderation", "reports", "settings", "technical", "support"}},
    "deputy": {"title": "Заместитель директора", "rank": 80, "permissions": {"staff_manage", "staff_view", "moderation", "reports", "settings", "support"}},
    "chief_curator": {"title": "Главный куратор", "rank": 70, "permissions": {"staff_view", "moderation", "reports", "settings"}},
    "curator": {"title": "Куратор", "rank": 60, "permissions": {"staff_view", "moderation", "reports"}},
    "chief_admin": {"title": "Главный администратор", "rank": 55, "permissions": {"staff_view", "moderation", "reports", "settings"}},
    "admin": {"title": "Администратор", "rank": 50, "permissions": {"moderation", "reports"}},
    "moderator": {"title": "Модератор", "rank": 30, "permissions": {"moderation", "reports"}},
    "developer": {"title": "Разработчик", "rank": 45, "permissions": {"staff_view", "technical"}},
    "senior_mod": {"title": "Старший модератор", "rank": 40, "permissions": {"moderation", "reports"}},
    "tech_admin": {"title": "Технический администратор", "rank": 38, "permissions": {"technical"}},
    "support_lead": {"title": "Главный специалист поддержки", "rank": 25, "permissions": {"support", "reports"}},
    "junior_mod": {"title": "Младший модератор", "rank": 20, "permissions": {"moderation", "reports"}},
    "support": {"title": "Специалист поддержки", "rank": 15, "permissions": {"support"}},
    "trainee": {"title": "Стажёр", "rank": 10, "permissions": {"reports"}},
}

# Keep historical role keys readable until existing assignments are migrated.
ROLES.update(LEGACY_ROLES)

ALIASES = {key: key for key in ROLES}
ALIASES.update({item["title"].lower().replace(" ", "_"): key for key, item in ROLES.items()})
ALIASES.update({
    # Explicit canonical titles take precedence over legacy display-name collisions.
    "главный_администратор": "head_administrator",
    "администратор": "administrator",
    "модератор": "chat_moderator",
    "владелец_проекта": "owner",
    "владелец": "owner",
})


def role_key(value: str) -> str | None:
    key = "_".join(value.strip().lower().replace("-", " ").split())
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


def role_rank(key: str | None) -> int:
    """Return the numeric authority of a global system role."""
    if key in {"owner", "project_owner"}:
        return 100
    return int(ROLES.get(key or "", {}).get("rank", 0))


def can_manage_rank(actor_rank: int, target_rank: int) -> bool:
    """A staff member may manage only strictly lower-ranked users."""
    return actor_rank > target_rank


def _role_label(key: str | None) -> str:
    if key in {"owner", "project_owner"}:
        return "Владелец проекта"
    return ROLES.get(key or "", {}).get("title", "Без должности")


async def staff_command(message: Message, owner_id: int) -> None:
    if not message.from_user or not await has_permission(message.from_user.id, owner_id, "staff_view"):
        await _deny(message)
        return
    rows = await database.list_system_staff()
    lines = ["👥 <b>Команда F-rum-Bot</b>", f"👑 Владелец проекта: <code>{owner_id}</code>"]
    grouped: dict[str, list[str]] = {}
    for row in rows:
        key = row["role_key"]
        role = ROLE_CATALOG.get(key)
        department = DEPARTMENT_TITLES.get(role.department, "Прочие должности") if role else "Старые должности"
        grouped.setdefault(department, []).append(
            f"• <b>{escape(_role_label(key))}</b> — <code>{row['user_id']}</code>"
        )
    for department, members in grouped.items():
        lines.extend(["", f"<b>{escape(department)}</b>", *members])
    if not rows:
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
    permissions = sorted(ROLES.get(role or "", {}).get("permissions", set()))
    await message.answer(
        f"👤 <b>Карточка сотрудника</b>\nID: <code>{target_id}</code>"
        f"\nДолжность: <b>{escape(_role_label(role))}</b>"
        f"\nПолномочия: <code>{escape(', '.join(permissions) or 'нет')}</code>",
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
            await message.reply("Формат: /setrole TELEGRAM_ID КЛЮЧ\nДоступные ключи: " + ", ".join(ROLE_CATALOG))
            return
        target_raw, requested_role = parts[1], parts[2]
    if not target_raw.isdigit():
        await message.reply("Telegram ID должен быть числом.")
        return
    target_id = int(target_raw)
    key = role_key(requested_role)
    if not key or key == "owner":
        await message.reply("Неизвестная или защищённая должность. Должность владельца назначается только через OWNER_TELEGRAM_ID.")
        return
    if target_id == owner_id or target_id == actor_id:
        await message.reply("Нельзя изменить должность владельца или самого себя.")
        return
    role_ranks = {role_key: data["rank"] for role_key, data in ROLES.items()}
    assigned = await database.assign_system_role_guarded(
        target_id, key, actor_id, owner_id, role_ranks
    )
    if not assigned:
        await message.reply("⛔ Нельзя назначать равную/старшую должность или менять сотрудника равного/старшего уровня.")
        return
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
    role_ranks = {role_key: data["rank"] for role_key, data in ROLES.items()}
    removed = await database.remove_system_role_guarded(
        target_id, message.from_user.id, owner_id, role_ranks
    )
    if not removed:
        await message.reply("Нельзя снимать сотрудника равного или более высокого уровня либо сотрудник не найден.")
        return
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
        "🛠 <b>Техническая диагностика F-rum-Bot</b>\n"
        f"{db_status}\n"
        "Токен Telegram: " + ("настроен" if os.getenv("TELEGRAM_BOT_TOKEN") else "не настроен") + "\n"
        "XenForo API: " + ("настроен" if os.getenv("XF_API_KEY") else "не настроен"),
        parse_mode="HTML",
    )


async def rolehelp_command(message: Message, owner_id: int) -> None:
    role = await get_role(message.from_user.id, owner_id) if message.from_user else None
    permissions = set() if role not in ROLES else ROLES[role]["permissions"]
    lines = [
        f"🧭 <b>Должность:</b> {escape(_role_label(role))}",
        "",
        "<b>Команды команды</b>",
        "/myrole — моя должность",
        "/rolehelp — справка",
    ]
    if role == "owner" or "staff_view" in permissions:
        lines.extend(["/staff — состав команды", "/staffinfo ID — карточка сотрудника", "/stafflog — журнал назначений"])
    if role == "owner" or "staff_manage" in permissions:
        lines.extend(["/setrole ID КЛЮЧ — назначить должность", "/staffremove ID — снять должность",
                      "", "<b>Ключи должностей:</b>"] + [f"{key} — {data['title']}" for key, data in ROLE_CATALOG.items()])
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
    if "testing_review" in permissions:
        lines.extend(["", "<b>Контроль качества:</b> доступ к проверке результатов тестирования"])
    if "organizations" in permissions:
        lines.extend(["", "<b>Организации:</b> доступ к направлению организаций"])
    if "discord_moderation" in permissions:
        lines.extend(["", "<b>Discord:</b> полномочия направления Discord"])
    await message.answer("\n".join(lines), parse_mode="HTML")


async def reporthelp_command(message: Message, owner_id: int) -> None:
    if not message.from_user or not await has_permission(message.from_user.id, owner_id, "support"):
        await _deny(message)
        return
    await message.answer(
        "🎧 <b>Регламент поддержки</b>\n"
        "1. Уточните проблему и Telegram ID пользователя.\n"
        "2. Не запрашивайте пароли, коды входа или токены.\n"
        "3. Для нарушений используйте /report в подключённой группе.\n"
        "4. Передайте техническую неисправность разработчику.",
        parse_mode="HTML",
    )


async def _deny(message: Message) -> None:
    await message.answer("⛔ Недостаточно полномочий для этой команды.")
