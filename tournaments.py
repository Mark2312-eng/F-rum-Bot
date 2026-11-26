"""Family tournaments with registration and deterministic virtual prizes."""
from html import escape

from aiogram.filters import CommandObject
from aiogram.types import Message

from database import database


def format_tournaments(rows: list) -> str:
    if not rows:
        return "🏆 <b>Турниры семей</b>\\n\\nПока турниров нет. Глава семьи может создать турнир."
    lines = ["🏆 <b>Турниры семей</b>", ""]
    for row in rows:
        status = "🟢 Регистрация" if row["status"] == "open" else "🏁 Завершён"
        lines.append(
            f"#{row['id']} <b>{escape(row['name'])}</b>\\n"
            f"Статус: {status} · Семей: {row['family_count']}\\n"
            f"Приз: {row['prize_coins']} игровых монет"
            + (f"\\nПобедитель: <b>{escape(row['winner_name'])}</b>" if row["winner_name"] else "")
        )
    lines.extend([
        "",
        "Команды: /tournament create Название 500",
        "/tournament join ID",
        "/tournament finish ID FAMILY_ID",
    ])
    return "\\n\\n".join(lines)


async def show_tournaments(message: Message) -> None:
    rows = await database.get_game_tournaments()
    await message.answer(format_tournaments(rows), parse_mode="HTML")


async def manage_tournament(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    args = (command.args or "").strip()
    parts = args.split()
    if not parts:
        await message.answer(
            "Использование:\\n"
            "<code>/tournament create Название 500</code> — создать турнир и указать общий приз\\n"
            "<code>/tournament join ID</code> — зарегистрировать семью\\n"
            "<code>/tournament finish ID FAMILY_ID</code> — завершить турнир и указать победителя",
            parse_mode="HTML",
        )
        return
    action = parts[0].lower()
    user_id = message.from_user.id
    if action == "create":
        if len(parts) < 3 or not parts[-1].isdigit():
            await message.answer("Формат: /tournament create Название 500")
            return
        name = " ".join(parts[1:-1])
        prize = int(parts[-1])
        status, tournament_id = await database.create_game_tournament(user_id, name, prize)
        responses = {
            "ok": f"✅ Турнир создан. ID: <code>{tournament_id}</code>. Семья создателя зарегистрирована автоматически.",
            "not_owner": "⛔ Создавать турниры может только глава семьи.",
            "invalid": "⚠️ Название: 3–48 символов. Приз: от 0 до 5000 игровых монет.",
        }
        await message.answer(responses[status], parse_mode="HTML")
    elif action == "join":
        tournament_id = int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else 0
        status = await database.join_game_tournament(user_id, tournament_id)
        responses = {
            "joined": "✅ Семья зарегистрирована в турнире.",
            "already": "ℹ️ Эта семья уже участвует.",
            "not_owner": "⛔ Зарегистрировать семью может только её глава.",
            "missing": "⚠️ Турнир не найден.",
            "closed": "⚠️ Регистрация на этот турнир закрыта.",
        }
        await message.answer(responses[status])
    elif action == "finish":
        valid = len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit()
        if not valid:
            await message.answer("Формат: /tournament finish ID FAMILY_ID")
            return
        status, prize = await database.finish_game_tournament(
            user_id, int(parts[1]), int(parts[2])
        )
        responses = {
            "ok": f"🏁 Турнир завершён. Победителям распределён общий приз: {prize} игровых монет.",
            "missing": "⚠️ Турнир не найден.",
            "forbidden": "⛔ Завершить турнир может только его организатор.",
            "finished": "ℹ️ Турнир уже завершён.",
            "not_enrolled": "⚠️ Указанная семья не зарегистрирована в этом турнире.",
            "empty": "⚠️ В семье-победителе нет участников.",
        }
        await message.answer(responses[status])
    else:
        await message.answer("Доступно: create, join, finish. Подробности: /tournament")
