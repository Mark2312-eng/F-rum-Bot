"""PostgreSQL persistence for Telegram moderation state."""
import os

import asyncpg


class Database:
    def __init__(self) -> None:
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url:
            raise RuntimeError("DATABASE_URL is missing; refusing to run moderation without persistent storage")
        self.pool = await asyncpg.create_pool(
            dsn=database_url,
            min_size=1,
            max_size=5,
            command_timeout=10,
            ssl="require",
        )
        async with self.pool.acquire() as connection:
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS registered_chats (
                    chat_id BIGINT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    connected_by BIGINT NOT NULL,
                    moderation_mode TEXT NOT NULL DEFAULT 'balanced',
                    link_policy TEXT NOT NULL DEFAULT 'block',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                ALTER TABLE registered_chats
                    ADD COLUMN IF NOT EXISTS moderation_mode TEXT NOT NULL DEFAULT 'balanced';
                ALTER TABLE registered_chats
                    ADD COLUMN IF NOT EXISTS link_policy TEXT NOT NULL DEFAULT 'block';
                CREATE TABLE IF NOT EXISTS moderation_warnings (
                    chat_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    warning_count INTEGER NOT NULL DEFAULT 0 CHECK (warning_count >= 0),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (chat_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS moderation_events (
                    id BIGSERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    actor_id BIGINT,
                    target_id BIGINT,
                    action TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS moderation_events_chat_created_idx
                    ON moderation_events (chat_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS game_players (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT NOT NULL DEFAULT '',
                    xp BIGINT NOT NULL DEFAULT 0 CHECK (xp >= 0),
                    coins BIGINT NOT NULL DEFAULT 0 CHECK (coins >= 0),
                    reputation INTEGER NOT NULL DEFAULT 0,
                    daily_streak INTEGER NOT NULL DEFAULT 0 CHECK (daily_streak >= 0),
                    last_daily_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS game_players_xp_idx ON game_players (xp DESC, user_id ASC);
                CREATE TABLE IF NOT EXISTS game_achievements (
                    user_id BIGINT NOT NULL REFERENCES game_players(user_id) ON DELETE CASCADE,
                    achievement_code TEXT NOT NULL,
                    unlocked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (user_id, achievement_code)
                );
                CREATE TABLE IF NOT EXISTS game_families (
                    id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                    owner_id BIGINT NOT NULL REFERENCES game_players(user_id),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS game_family_members (
                    family_id BIGINT NOT NULL REFERENCES game_families(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL REFERENCES game_players(user_id) ON DELETE CASCADE,
                    role TEXT NOT NULL DEFAULT 'member', joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (family_id, user_id), UNIQUE (user_id)
                );
                CREATE TABLE IF NOT EXISTS game_government_departments (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    base_salary INTEGER NOT NULL DEFAULT 100 CHECK (base_salary >= 0),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS game_government_employees (
                    user_id BIGINT PRIMARY KEY REFERENCES game_players(user_id) ON DELETE CASCADE,
                    department_id BIGINT NOT NULL REFERENCES game_government_departments(id),
                    position TEXT NOT NULL DEFAULT 'Сотрудник',
                    hired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_salary_at TIMESTAMPTZ
                );
                CREATE INDEX IF NOT EXISTS game_government_department_idx
                    ON game_government_employees (department_id);
                CREATE TABLE IF NOT EXISTS game_government_tasks (
                    id BIGSERIAL PRIMARY KEY,
                    department_id BIGINT NOT NULL REFERENCES game_government_departments(id) ON DELETE CASCADE,
                    assigned_to BIGINT NOT NULL REFERENCES game_players(user_id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    reward_coins INTEGER NOT NULL DEFAULT 50 CHECK (reward_coins >= 0),
                    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'completed')),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at TIMESTAMPTZ
                );
                INSERT INTO game_government_departments (name, description, base_salary)
                VALUES
                    ('Мэрия', 'Городское управление и административные поручения.', 150),
                    ('Городское благоустройство', 'Порядок, инфраструктура и общественные проекты.', 120),
                    ('Транспортный департамент', 'Городской транспорт и дорожные проекты.', 130)
                ON CONFLICT (name) DO NOTHING;
                CREATE TABLE IF NOT EXISTS game_factions (
                    id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT ''
                );
                ALTER TABLE game_factions ADD COLUMN IF NOT EXISTS leader_id BIGINT REFERENCES game_players(user_id) ON DELETE SET NULL;
                CREATE TABLE IF NOT EXISTS game_faction_members (
                    faction_id BIGINT NOT NULL REFERENCES game_factions(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL REFERENCES game_players(user_id) ON DELETE CASCADE,
                    rank_name TEXT NOT NULL DEFAULT 'Новичок', joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (faction_id, user_id), UNIQUE (user_id)
                );
                ALTER TABLE game_faction_members ALTER COLUMN rank_name SET DEFAULT 'Рекрут';
                UPDATE game_faction_members SET rank_name = 'Рекрут' WHERE rank_name = 'Новичок';
                INSERT INTO game_factions (name, description)
                VALUES
                    ('Правительство Москвы', 'Городские службы и управление городом.'),
                    ('Армия России', 'Военная организация игрового мира.'),
                    ('ФСБ', 'Государственная служба безопасности игрового мира.')
                ON CONFLICT (name) DO NOTHING;
                CREATE TABLE IF NOT EXISTS game_inventory (
                    user_id BIGINT NOT NULL REFERENCES game_players(user_id) ON DELETE CASCADE,
                    item_code TEXT NOT NULL, quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    PRIMARY KEY (user_id, item_code)
                );
                CREATE TABLE IF NOT EXISTS game_properties (
                    id BIGSERIAL PRIMARY KEY,
                    owner_id BIGINT NOT NULL REFERENCES game_players(user_id) ON DELETE CASCADE,
                    property_type TEXT NOT NULL, name TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS game_jobs (
                    id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '', starting_rank TEXT NOT NULL DEFAULT 'Стажёр',
                    reward_coins INTEGER NOT NULL DEFAULT 0 CHECK (reward_coins >= 0),
                    active BOOLEAN NOT NULL DEFAULT TRUE
                );
                CREATE TABLE IF NOT EXISTS game_employment (
                    user_id BIGINT PRIMARY KEY REFERENCES game_players(user_id) ON DELETE CASCADE,
                    job_id BIGINT NOT NULL REFERENCES game_jobs(id),
                    rank_name TEXT NOT NULL DEFAULT 'Стажёр',
                    shifts_completed INTEGER NOT NULL DEFAULT 0 CHECK (shifts_completed >= 0),
                    hired_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                ALTER TABLE game_employment
                    ADD COLUMN IF NOT EXISTS last_shift_at TIMESTAMPTZ;
                INSERT INTO game_jobs (name, description, starting_rank, reward_coins)
                VALUES
                    ('Курьер', 'Доставка заказов по городу.', 'Стажёр', 75),
                    ('Таксист', 'Перевозка пассажиров по городу.', 'Стажёр', 90),
                    ('Механик', 'Обслуживание и ремонт транспорта.', 'Стажёр', 100),
                    ('Работник мэрии', 'Помощь городским службам.', 'Стажёр', 110)
                ON CONFLICT (name) DO NOTHING;
                CREATE TABLE IF NOT EXISTS game_shop_items (
                    code TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                    price INTEGER NOT NULL CHECK (price >= 0), active BOOLEAN NOT NULL DEFAULT TRUE
                );
                INSERT INTO game_shop_items (code, name, description, price)
                VALUES
                    ('water', 'Вода', 'Восстанавливает силы персонажа в будущих игровых механиках.', 25),
                    ('snack', 'Перекус', 'Небольшой запас еды для персонажа.', 40),
                    ('toolkit', 'Набор инструментов', 'Полезный предмет для игровых профессий.', 250),
                    ('first_aid', 'Аптечка', 'Предмет первой помощи в игровом инвентаре.', 180)
                ON CONFLICT (code) DO NOTHING;
                CREATE TABLE IF NOT EXISTS game_property_catalog (
                    code TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                    price INTEGER NOT NULL CHECK (price >= 0), active BOOLEAN NOT NULL DEFAULT TRUE
                );
                INSERT INTO game_property_catalog (code, name, description, price)
                VALUES
                    ('room', 'Комната', 'Небольшое личное жильё.', 2500),
                    ('apartment', 'Квартира', 'Уютная городская квартира.', 12000),
                    ('house', 'Дом', 'Отдельный жилой дом.', 45000)
                ON CONFLICT (code) DO NOTHING;
                CREATE TABLE IF NOT EXISTS game_vehicle_catalog (
                    code TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                    price INTEGER NOT NULL CHECK (price >= 0), active BOOLEAN NOT NULL DEFAULT TRUE
                );
                INSERT INTO game_vehicle_catalog (code, name, description, price)
                VALUES
                    ('bicycle', 'Велосипед', 'Простой городской транспорт.', 900),
                    ('scooter', 'Скутер', 'Компактный двухколёсный транспорт.', 4500),
                    ('sedan', 'Седан', 'Личный городской автомобиль.', 18000),
                    ('suv', 'Внедорожник', 'Просторный автомобиль.', 32000)
                ON CONFLICT (code) DO NOTHING;
                CREATE TABLE IF NOT EXISTS game_vehicles (
                    id BIGSERIAL PRIMARY KEY,
                    owner_id BIGINT NOT NULL REFERENCES game_players(user_id) ON DELETE CASCADE,
                    vehicle_code TEXT NOT NULL REFERENCES game_vehicle_catalog(code),
                    purchased_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS game_vehicles_owner_idx ON game_vehicles (owner_id, purchased_at DESC);
                CREATE TABLE IF NOT EXISTS game_events (
                    id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                    starts_at TIMESTAMPTZ NOT NULL, ends_at TIMESTAMPTZ,
                    reward_coins INTEGER NOT NULL DEFAULT 0 CHECK (reward_coins >= 0),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS game_quest_progress (
                    user_id BIGINT NOT NULL REFERENCES game_players(user_id) ON DELETE CASCADE,
                    quest_code TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0 CHECK (progress >= 0),
                    completed_at TIMESTAMPTZ, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (user_id, quest_code)
                );
                CREATE TABLE IF NOT EXISTS game_quest_catalog (
                    code TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
                    objective TEXT NOT NULL CHECK (objective IN ('shift', 'item', 'faction')),
                    reward_coins INTEGER NOT NULL CHECK (reward_coins >= 0),
                    reward_xp INTEGER NOT NULL CHECK (reward_xp >= 0),
                    reward_reputation INTEGER NOT NULL CHECK (reward_reputation >= 0),
                    active BOOLEAN NOT NULL DEFAULT TRUE
                );
                INSERT INTO game_quest_catalog
                    (code, title, description, objective, reward_coins, reward_xp, reward_reputation)
                VALUES
                    ('first_shift', 'Первый рабочий день', 'Заверши хотя бы одну рабочую смену.', 'shift', 150, 100, 2),
                    ('collector', 'Собиратель', 'Купи хотя бы один предмет в игровом магазине.', 'item', 75, 60, 1),
                    ('team_player', 'Командный игрок', 'Вступи в одну из игровых фракций.', 'faction', 100, 80, 3)
                ON CONFLICT (code) DO NOTHING;
                CREATE TABLE IF NOT EXISTS game_city_event_signups (
                    event_code TEXT NOT NULL,
                    user_id BIGINT NOT NULL REFERENCES game_players(user_id) ON DELETE CASCADE,
                    username TEXT NOT NULL DEFAULT '',
                    signed_up_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (event_code, user_id)
                );
                CREATE TABLE IF NOT EXISTS game_tournaments (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    organizer_id BIGINT NOT NULL REFERENCES game_players(user_id),
                    prize_coins INTEGER NOT NULL CHECK (prize_coins BETWEEN 0 AND 5000),
                    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'finished')),
                    winner_family_id BIGINT REFERENCES game_families(id),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    finished_at TIMESTAMPTZ
                );
                CREATE TABLE IF NOT EXISTS game_tournament_families (
                    tournament_id BIGINT NOT NULL REFERENCES game_tournaments(id) ON DELETE CASCADE,
                    family_id BIGINT NOT NULL REFERENCES game_families(id) ON DELETE CASCADE,
                    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (tournament_id, family_id)
                );
            """)

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    def _require_pool(self) -> asyncpg.Pool:
        if self.pool is None:
            raise RuntimeError("Database is not connected")
        return self.pool

    async def register_chat(self, chat_id: int, title: str, owner_id: int) -> None:
        pool = self._require_pool()
        await pool.execute(
            """INSERT INTO registered_chats (chat_id, title, connected_by)
               VALUES ($1, $2, $3)
               ON CONFLICT (chat_id) DO UPDATE
               SET title = EXCLUDED.title, connected_by = EXCLUDED.connected_by""",
            chat_id, title, owner_id,
        )

    async def is_chat_registered(self, chat_id: int) -> bool:
        pool = self._require_pool()
        return await pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM registered_chats WHERE chat_id = $1)",
            chat_id,
        )

    async def get_chat_settings(self, chat_id: int) -> dict[str, str]:
        pool = self._require_pool()
        row = await pool.fetchrow(
            "SELECT moderation_mode, link_policy FROM registered_chats WHERE chat_id = $1",
            chat_id,
        )
        if row is None:
            raise ValueError("Chat is not registered")
        return {"moderation_mode": row["moderation_mode"], "link_policy": row["link_policy"]}

    async def update_chat_setting(self, chat_id: int, setting: str, value: str) -> None:
        allowed = {
            "moderation_mode": {"off", "balanced", "strict"},
            "link_policy": {"allow", "block", "mute"},
        }
        if setting not in allowed or value not in allowed[setting]:
            raise ValueError("Unsupported moderation setting")
        pool = self._require_pool()
        column = setting
        await pool.execute(
            f"UPDATE registered_chats SET {column} = $2 WHERE chat_id = $1",
            chat_id, value,
        )

    async def log_moderation_event(
        self, chat_id: int, actor_id: int | None, target_id: int | None,
        action: str, details: str = "",
    ) -> None:
        pool = self._require_pool()
        await pool.execute(
            """INSERT INTO moderation_events
               (chat_id, actor_id, target_id, action, details)
               VALUES ($1, $2, $3, $4, $5)""",
            chat_id, actor_id, target_id, action, details[:240],
        )

    async def get_recent_moderation_events(self, chat_id: int, limit: int = 10) -> list[asyncpg.Record]:
        pool = self._require_pool()
        safe_limit = max(1, min(int(limit), 20))
        return await pool.fetch(
            """SELECT actor_id, target_id, action, details, created_at
               FROM moderation_events
               WHERE chat_id = $1
               ORDER BY created_at DESC, id DESC
               LIMIT $2""",
            chat_id, safe_limit,
        )

    async def registered_chat_count(self) -> int:
        pool = self._require_pool()
        return int(await pool.fetchval("SELECT COUNT(*) FROM registered_chats"))

    async def add_warning(self, chat_id: int, user_id: int) -> int:
        pool = self._require_pool()
        return int(await pool.fetchval(
            """INSERT INTO moderation_warnings (chat_id, user_id, warning_count)
               VALUES ($1, $2, 1)
               ON CONFLICT (chat_id, user_id) DO UPDATE
               SET warning_count = moderation_warnings.warning_count + 1,
                   updated_at = NOW()
               RETURNING warning_count""",
            chat_id, user_id,
        ))

    async def reset_warnings(self, chat_id: int, user_id: int) -> None:
        pool = self._require_pool()
        await pool.execute(
            """INSERT INTO moderation_warnings (chat_id, user_id, warning_count)
               VALUES ($1, $2, 0)
               ON CONFLICT (chat_id, user_id) DO UPDATE
               SET warning_count = 0, updated_at = NOW()""",
            chat_id, user_id,
        )


    async def get_game_profile(self, user_id: int, username: str = "") -> asyncpg.Record:
        pool = self._require_pool()
        return await pool.fetchrow(
            """INSERT INTO game_players (user_id, username) VALUES ($1, $2)
               ON CONFLICT (user_id) DO UPDATE
               SET username = CASE WHEN EXCLUDED.username <> '' THEN EXCLUDED.username
                                   ELSE game_players.username END,
                   updated_at = NOW()
               RETURNING user_id, username, xp, coins, reputation, daily_streak,
                         last_daily_at, created_at""",
            user_id, username[:64],
        )

    async def claim_game_daily(self, user_id: int, username: str = "") -> tuple[asyncpg.Record, int, bool]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """INSERT INTO game_players (user_id, username) VALUES ($1, $2)
                       ON CONFLICT (user_id) DO UPDATE
                       SET username = CASE WHEN EXCLUDED.username <> '' THEN EXCLUDED.username
                                           ELSE game_players.username END,
                           updated_at = NOW()""",
                    user_id, username[:64],
                )
                player = await connection.fetchrow(
                    """SELECT user_id, username, xp, coins, reputation, daily_streak, last_daily_at
                       FROM game_players WHERE user_id = $1 FOR UPDATE""",
                    user_id,
                )
                today = await connection.fetchval("SELECT CURRENT_DATE")
                yesterday = await connection.fetchval("SELECT CURRENT_DATE - 1")
                last_day = player["last_daily_at"].date() if player["last_daily_at"] else None
                if last_day == today:
                    return player, 0, False
                streak = player["daily_streak"] + 1 if last_day == yesterday else 1
                reward = 100 + min(streak - 1, 6) * 25
                updated = await connection.fetchrow(
                    """UPDATE game_players
                       SET xp = xp + 50, coins = coins + $2, daily_streak = $3,
                           last_daily_at = NOW(), updated_at = NOW()
                       WHERE user_id = $1
                       RETURNING user_id, username, xp, coins, reputation, daily_streak, last_daily_at""",
                    user_id, reward, streak,
                )
                return updated, reward, True

    async def get_game_leaderboard(self, limit: int = 10) -> list[asyncpg.Record]:
        pool = self._require_pool()
        safe_limit = max(1, min(int(limit), 20))
        return await pool.fetch(
            """SELECT user_id, username, xp, coins, reputation FROM game_players
               ORDER BY xp DESC, created_at ASC LIMIT $1""",
            safe_limit,
        )

    async def sync_game_achievements(self, user_id: int) -> list[asyncpg.Record]:
        pool = self._require_pool()
        await pool.execute(
            """INSERT INTO game_achievements (user_id, achievement_code)
               SELECT user_id, code FROM game_players
               CROSS JOIN (VALUES
                   ('first_steps', xp >= 50),
                   ('experienced', xp >= 500),
                   ('wealthy', coins >= 1000),
                   ('reputation', reputation >= 100)
               ) AS achievements(code, achieved)
               WHERE user_id = $1 AND achieved
               ON CONFLICT (user_id, achievement_code) DO NOTHING""",
            user_id,
        )
        return await pool.fetch(
            """SELECT achievement_code, unlocked_at FROM game_achievements
               WHERE user_id = $1 ORDER BY unlocked_at ASC""",
            user_id,
        )


    async def get_game_jobs(self) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            """SELECT id, name, description, starting_rank, reward_coins
               FROM game_jobs WHERE active = TRUE ORDER BY id"""
        )

    async def get_game_employment(self, user_id: int) -> asyncpg.Record | None:
        return await self._require_pool().fetchrow(
            """SELECT e.job_id, j.name AS job_name, j.description, j.reward_coins,
                      e.rank_name, e.shifts_completed, e.last_shift_at
               FROM game_employment e
               JOIN game_jobs j ON j.id = e.job_id
               WHERE e.user_id = $1""",
            user_id,
        )

    async def apply_game_job(self, user_id: int, username: str, job_id: int) -> tuple[bool, str]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """INSERT INTO game_players (user_id, username) VALUES ($1, $2)
                       ON CONFLICT (user_id) DO UPDATE
                       SET username = CASE WHEN EXCLUDED.username <> '' THEN EXCLUDED.username
                                           ELSE game_players.username END""",
                    user_id, username[:64],
                )
                existing = await connection.fetchval(
                    "SELECT job_id FROM game_employment WHERE user_id = $1 FOR UPDATE", user_id
                )
                if existing is not None:
                    return False, "У тебя уже есть работа. Сначала уволься."
                job = await connection.fetchrow(
                    "SELECT id, name, starting_rank FROM game_jobs WHERE id = $1 AND active = TRUE",
                    job_id,
                )
                if job is None:
                    return False, "Эта вакансия больше недоступна."
                await connection.execute(
                    """INSERT INTO game_employment (user_id, job_id, rank_name)
                       VALUES ($1, $2, $3)""",
                    user_id, job["id"], job["starting_rank"],
                )
                return True, f"Ты устроился на работу: {job['name']}."

    async def perform_game_shift(self, user_id: int) -> tuple[str, asyncpg.Record | None, int]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                employment = await connection.fetchrow(
                    """SELECT e.job_id, e.rank_name, e.shifts_completed, e.last_shift_at,
                              j.name AS job_name, j.reward_coins
                       FROM game_employment e JOIN game_jobs j ON j.id = e.job_id
                       WHERE e.user_id = $1 FOR UPDATE OF e""",
                    user_id,
                )
                if employment is None:
                    return "no_job", None, 0
                cooldown = await connection.fetchval(
                    """SELECT $1::timestamptz IS NOT NULL
                              AND $1::timestamptz > NOW() - INTERVAL '10 minutes'""",
                    employment["last_shift_at"],
                )
                if cooldown:
                    return "cooldown", employment, 0
                shifts = int(employment["shifts_completed"]) + 1
                reward = int(employment["reward_coins"])
                rank = employment["rank_name"]
                if shifts >= 20:
                    rank = "Руководитель"
                elif shifts >= 10:
                    rank = "Старший сотрудник"
                elif shifts >= 5:
                    rank = "Опытный сотрудник"
                await connection.execute(
                    """UPDATE game_employment
                       SET shifts_completed = $2, rank_name = $3, last_shift_at = NOW()
                       WHERE user_id = $1""",
                    user_id, shifts, rank,
                )
                await connection.execute(
                    """UPDATE game_players SET coins = coins + $2, xp = xp + 35,
                       updated_at = NOW() WHERE user_id = $1""",
                    user_id, reward,
                )
                updated = await connection.fetchrow(
                    """SELECT e.job_id, e.rank_name, e.shifts_completed, e.last_shift_at,
                              j.name AS job_name, j.reward_coins
                       FROM game_employment e JOIN game_jobs j ON j.id = e.job_id
                       WHERE e.user_id = $1""",
                    user_id,
                )
                return "ok", updated, reward

    async def quit_game_job(self, user_id: int) -> bool:
        result = await self._require_pool().execute(
            "DELETE FROM game_employment WHERE user_id = $1", user_id
        )
        return result.endswith("1")


    async def get_game_factions(self) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            """SELECT f.id, f.name, f.description, f.leader_id, COUNT(m.user_id)::int AS members
               FROM game_factions f LEFT JOIN game_faction_members m ON m.faction_id = f.id
               GROUP BY f.id ORDER BY f.id"""
        )

    async def get_game_faction(self, user_id: int) -> asyncpg.Record | None:
        return await self._require_pool().fetchrow(
            """SELECT f.id, f.name, f.description, m.rank_name, m.joined_at
               FROM game_faction_members m JOIN game_factions f ON f.id = m.faction_id
               WHERE m.user_id = $1""",
            user_id,
        )

    async def join_game_faction(self, user_id: int, username: str, faction_id: int) -> tuple[bool, str]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """INSERT INTO game_players (user_id, username) VALUES ($1, $2)
                       ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username""",
                    user_id, username[:64],
                )
                current = await connection.fetchval(
                    "SELECT faction_id FROM game_faction_members WHERE user_id = $1 FOR UPDATE",
                    user_id,
                )
                if current is not None:
                    return False, "Ты уже состоишь во фракции. Сначала выйди из неё."
                faction = await connection.fetchrow(
                    "SELECT id, name FROM game_factions WHERE id = $1", faction_id
                )
                if faction is None:
                    return False, "Фракция не найдена."
                await connection.execute(
                    "INSERT INTO game_faction_members (faction_id, user_id) VALUES ($1, $2)",
                    faction_id, user_id,
                )
                return True, f"Ты вступил во фракцию «{faction['name']}»."

    async def leave_game_faction(self, user_id: int) -> bool:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                membership = await connection.fetchrow(
                    """SELECT m.faction_id, f.leader_id
                       FROM game_faction_members m JOIN game_factions f ON f.id = m.faction_id
                       WHERE m.user_id = $1 FOR UPDATE OF m, f""", user_id
                )
                if membership is None or membership["leader_id"] == user_id:
                    return False
                result = await connection.execute(
                    "DELETE FROM game_faction_members WHERE user_id = $1", user_id
                )
                return result.endswith("1")

    async def create_game_family(self, user_id: int, username: str, name: str) -> tuple[bool, str]:
        clean_name = " ".join(name.split()).strip()
        if not 3 <= len(clean_name) <= 32:
            return False, "Название семьи должно содержать от 3 до 32 символов."
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """INSERT INTO game_players (user_id, username) VALUES ($1, $2)
                       ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username""",
                    user_id, username[:64],
                )
                existing = await connection.fetchval(
                    "SELECT family_id FROM game_family_members WHERE user_id = $1 FOR UPDATE",
                    user_id,
                )
                if existing is not None:
                    return False, "Ты уже состоишь в семье. Сначала выйди из неё."
                family_id = await connection.fetchval(
                    """INSERT INTO game_families (name, owner_id) VALUES ($1, $2)
                       ON CONFLICT (name) DO NOTHING RETURNING id""",
                    clean_name, user_id,
                )
                if family_id is None:
                    return False, "Семья с таким названием уже существует."
                await connection.execute(
                    """INSERT INTO game_family_members (family_id, user_id, role)
                       VALUES ($1, $2, 'owner')""",
                    family_id, user_id,
                )
                return True, f"Семья «{clean_name}» создана. Её ID: {family_id}."

    async def join_game_family(self, user_id: int, family_id: int) -> tuple[bool, str]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "INSERT INTO game_players (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING",
                    user_id,
                )
                existing = await connection.fetchval(
                    "SELECT family_id FROM game_family_members WHERE user_id = $1 FOR UPDATE",
                    user_id,
                )
                if existing is not None:
                    return False, "Ты уже состоишь в семье. Сначала выйди из неё."
                family = await connection.fetchrow(
                    "SELECT id, name FROM game_families WHERE id = $1 FOR UPDATE",
                    family_id,
                )
                if family is None:
                    return False, "Семья не найдена."
                member_count = await connection.fetchval(
                    "SELECT COUNT(*) FROM game_family_members WHERE family_id = $1",
                    family_id,
                )
                if member_count >= 10:
                    return False, "В семье уже максимальное количество участников (10)."
                await connection.execute(
                    """INSERT INTO game_family_members (family_id, user_id)
                       VALUES ($1, $2)""",
                    family_id, user_id,
                )
                return True, f"Ты вступил в семью «{family['name']}»."

    async def leave_game_family(self, user_id: int) -> tuple[bool, str]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                membership = await connection.fetchrow(
                    """SELECT m.family_id, m.role, f.name
                       FROM game_family_members m JOIN game_families f ON f.id = m.family_id
                       WHERE m.user_id = $1 FOR UPDATE OF m""",
                    user_id,
                )
                if membership is None:
                    return False, "Ты не состоишь в семье."
                if membership["role"] == "owner":
                    return False, "Глава не может покинуть семью. Передай главенство или распусти семью через поддержку."
                await connection.execute(
                    "DELETE FROM game_family_members WHERE user_id = $1", user_id
                )
                return True, f"Ты покинул семью «{membership['name']}»."

    async def get_game_family(self, user_id: int) -> asyncpg.Record | None:
        return await self._require_pool().fetchrow(
            """SELECT f.id, f.name, f.owner_id, m.role,
                      (SELECT COUNT(*)::int FROM game_family_members x WHERE x.family_id = f.id) AS members
               FROM game_family_members m JOIN game_families f ON f.id = m.family_id
               WHERE m.user_id = $1""",
            user_id,
        )


    async def get_game_shop_items(self) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            "SELECT code, name, description, price FROM game_shop_items WHERE active = TRUE ORDER BY price"
        )

    async def get_game_inventory(self, user_id: int) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            """SELECT i.item_code, i.quantity, s.name, s.description
               FROM game_inventory i LEFT JOIN game_shop_items s ON s.code = i.item_code
               WHERE i.user_id = $1 ORDER BY i.item_code""",
            user_id,
        )

    async def buy_game_item(self, user_id: int, username: str, code: str) -> tuple[str, int]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """INSERT INTO game_players (user_id, username) VALUES ($1, $2)
                       ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username""",
                    user_id, username[:64],
                )
                player = await connection.fetchrow(
                    "SELECT coins FROM game_players WHERE user_id = $1 FOR UPDATE", user_id
                )
                item = await connection.fetchrow(
                    "SELECT price FROM game_shop_items WHERE code = $1 AND active = TRUE", code
                )
                if item is None:
                    return "missing", 0
                price = int(item["price"])
                if int(player["coins"]) < price:
                    return "funds", price
                await connection.execute(
                    "UPDATE game_players SET coins = coins - $2, updated_at = NOW() WHERE user_id = $1",
                    user_id, price,
                )
                await connection.execute(
                    """INSERT INTO game_inventory (user_id, item_code, quantity)
                       VALUES ($1, $2, 1)
                       ON CONFLICT (user_id, item_code)
                       DO UPDATE SET quantity = game_inventory.quantity + 1""",
                    user_id, code,
                )
                return "ok", price

    async def get_game_property_catalog(self) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            "SELECT code, name, description, price FROM game_property_catalog WHERE active = TRUE ORDER BY price"
        )

    async def get_game_property(self, user_id: int) -> asyncpg.Record | None:
        return await self._require_pool().fetchrow(
            "SELECT id, property_type, name, created_at FROM game_properties WHERE owner_id = $1 ORDER BY id LIMIT 1",
            user_id,
        )

    async def buy_game_property(self, user_id: int, username: str, code: str) -> tuple[str, int]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """INSERT INTO game_players (user_id, username) VALUES ($1, $2)
                       ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username""",
                    user_id, username[:64],
                )
                player = await connection.fetchrow(
                    "SELECT coins FROM game_players WHERE user_id = $1 FOR UPDATE", user_id
                )
                owned = await connection.fetchval(
                    "SELECT id FROM game_properties WHERE owner_id = $1 LIMIT 1", user_id
                )
                if owned is not None:
                    return "owned", 0
                item = await connection.fetchrow(
                    "SELECT name, price FROM game_property_catalog WHERE code = $1 AND active = TRUE", code
                )
                if item is None:
                    return "missing", 0
                price = int(item["price"])
                if int(player["coins"]) < price:
                    return "funds", price
                await connection.execute(
                    "UPDATE game_players SET coins = coins - $2, updated_at = NOW() WHERE user_id = $1",
                    user_id, price,
                )
                await connection.execute(
                    "INSERT INTO game_properties (owner_id, property_type, name) VALUES ($1, $2, $3)",
                    user_id, code, item["name"],
                )
                return "ok", price

    async def get_game_vehicle_catalog(self) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            "SELECT code, name, description, price FROM game_vehicle_catalog WHERE active = TRUE ORDER BY price"
        )

    async def get_game_vehicles(self, user_id: int) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            """SELECT v.id, c.name, c.description, v.purchased_at
               FROM game_vehicles v JOIN game_vehicle_catalog c ON c.code = v.vehicle_code
               WHERE v.owner_id = $1 ORDER BY v.purchased_at DESC""",
            user_id,
        )

    async def buy_game_vehicle(self, user_id: int, username: str, code: str) -> tuple[str, int]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """INSERT INTO game_players (user_id, username) VALUES ($1, $2)
                       ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username""",
                    user_id, username[:64],
                )
                player = await connection.fetchrow(
                    "SELECT coins FROM game_players WHERE user_id = $1 FOR UPDATE", user_id
                )
                count = await connection.fetchval(
                    "SELECT COUNT(*) FROM game_vehicles WHERE owner_id = $1", user_id
                )
                if count >= 3:
                    return "limit", 0
                item = await connection.fetchrow(
                    "SELECT price FROM game_vehicle_catalog WHERE code = $1 AND active = TRUE", code
                )
                if item is None:
                    return "missing", 0
                price = int(item["price"])
                if int(player["coins"]) < price:
                    return "funds", price
                await connection.execute(
                    "UPDATE game_players SET coins = coins - $2, updated_at = NOW() WHERE user_id = $1",
                    user_id, price,
                )
                await connection.execute(
                    "INSERT INTO game_vehicles (owner_id, vehicle_code) VALUES ($1, $2)",
                    user_id, code,
                )
                return "ok", price


    async def get_game_quests(self, user_id: int) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            """SELECT q.code, q.title, q.description, q.reward_coins, q.reward_xp,
                      q.reward_reputation, p.completed_at,
                      CASE q.objective
                        WHEN 'shift' THEN EXISTS (
                            SELECT 1 FROM game_employment e
                            WHERE e.user_id = $1 AND e.shifts_completed >= 1
                        )
                        WHEN 'item' THEN EXISTS (
                            SELECT 1 FROM game_inventory i
                            WHERE i.user_id = $1 AND i.quantity >= 1
                        )
                        WHEN 'faction' THEN EXISTS (
                            SELECT 1 FROM game_faction_members f WHERE f.user_id = $1
                        )
                        ELSE FALSE
                      END AS ready
               FROM game_quest_catalog q
               LEFT JOIN game_quest_progress p
                 ON p.user_id = $1 AND p.quest_code = q.code
               WHERE q.active = TRUE ORDER BY q.code""",
            user_id,
        )

    async def claim_game_quest(self, user_id: int, username: str, code: str) -> tuple[str, int, int, int]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """INSERT INTO game_players (user_id, username) VALUES ($1, $2)
                       ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username""",
                    user_id, username[:64],
                )
                await connection.fetchrow(
                    "SELECT user_id FROM game_players WHERE user_id = $1 FOR UPDATE", user_id
                )
                quest = await connection.fetchrow(
                    """SELECT code, objective, reward_coins, reward_xp, reward_reputation
                       FROM game_quest_catalog WHERE code = $1 AND active = TRUE""",
                    code,
                )
                if quest is None:
                    return "missing", 0, 0, 0
                completed = await connection.fetchval(
                    "SELECT completed_at FROM game_quest_progress WHERE user_id = $1 AND quest_code = $2",
                    user_id, code,
                )
                if completed is not None:
                    return "claimed", 0, 0, 0
                checks = {
                    "shift": """SELECT EXISTS (SELECT 1 FROM game_employment
                               WHERE user_id = $1 AND shifts_completed >= 1)""",
                    "item": """SELECT EXISTS (SELECT 1 FROM game_inventory
                              WHERE user_id = $1 AND quantity >= 1)""",
                    "faction": """SELECT EXISTS (SELECT 1 FROM game_faction_members
                                 WHERE user_id = $1)""",
                }
                ready = await connection.fetchval(checks[quest["objective"]], user_id)
                if not ready:
                    return "not_ready", 0, 0, 0
                coins = int(quest["reward_coins"])
                xp = int(quest["reward_xp"])
                reputation = int(quest["reward_reputation"])
                await connection.execute(
                    """INSERT INTO game_quest_progress (user_id, quest_code, progress, completed_at)
                       VALUES ($1, $2, 1, NOW())""",
                    user_id, code,
                )
                await connection.execute(
                    """UPDATE game_players
                       SET coins = coins + $2, xp = xp + $3,
                           reputation = reputation + $4, updated_at = NOW()
                       WHERE user_id = $1""",
                    user_id, coins, xp, reputation,
                )
                return "ok", coins, xp, reputation

    async def get_game_reputation(self, user_id: int) -> asyncpg.Record | None:
        return await self._require_pool().fetchrow(
            """SELECT username, xp, coins, reputation FROM game_players
               WHERE user_id = $1""",
            user_id,
        )



    async def create_game_tournament(self, user_id: int, name: str, prize_coins: int) -> tuple[str, int]:
        clean_name = " ".join(name.split()).strip()
        if not 3 <= len(clean_name) <= 48 or not 0 <= prize_coins <= 5000:
            return "invalid", 0
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                family = await connection.fetchrow(
                    """SELECT f.id FROM game_families f
                       JOIN game_family_members m ON m.family_id = f.id
                       WHERE m.user_id = $1 AND m.role = 'owner'""", user_id
                )
                if family is None:
                    return "not_owner", 0
                tournament_id = await connection.fetchval(
                    """INSERT INTO game_tournaments (name, organizer_id, prize_coins)
                       VALUES ($1, $2, $3) RETURNING id""", clean_name, user_id, prize_coins
                )
                await connection.execute(
                    "INSERT INTO game_tournament_families (tournament_id, family_id) VALUES ($1, $2)",
                    tournament_id, family["id"]
                )
                return "ok", int(tournament_id)

    async def join_game_tournament(self, user_id: int, tournament_id: int) -> str:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                family = await connection.fetchrow(
                    """SELECT f.id FROM game_families f
                       JOIN game_family_members m ON m.family_id = f.id
                       WHERE m.user_id = $1 AND m.role = 'owner'""", user_id
                )
                if family is None:
                    return "not_owner"
                tournament = await connection.fetchrow(
                    "SELECT id, status FROM game_tournaments WHERE id = $1 FOR UPDATE", tournament_id
                )
                if tournament is None:
                    return "missing"
                if tournament["status"] != "open":
                    return "closed"
                result = await connection.execute(
                    """INSERT INTO game_tournament_families (tournament_id, family_id)
                       VALUES ($1, $2) ON CONFLICT DO NOTHING""", tournament_id, family["id"]
                )
                return "joined" if result.endswith("1") else "already"

    async def finish_game_tournament(self, user_id: int, tournament_id: int, winner_family_id: int) -> tuple[str, int]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                tournament = await connection.fetchrow(
                    "SELECT * FROM game_tournaments WHERE id = $1 FOR UPDATE", tournament_id
                )
                if tournament is None:
                    return "missing", 0
                if int(tournament["organizer_id"]) != user_id:
                    return "forbidden", 0
                if tournament["status"] != "open":
                    return "finished", 0
                enrolled = await connection.fetchval(
                    """SELECT EXISTS (SELECT 1 FROM game_tournament_families
                       WHERE tournament_id = $1 AND family_id = $2)""", tournament_id, winner_family_id
                )
                if not enrolled:
                    return "not_enrolled", 0
                members = await connection.fetch(
                    "SELECT user_id FROM game_family_members WHERE family_id = $1 ORDER BY user_id",
                    winner_family_id
                )
                if not members:
                    return "empty", 0
                prize = int(tournament["prize_coins"])
                share, remainder = divmod(prize, len(members))
                for index, member in enumerate(members):
                    await connection.execute(
                        "UPDATE game_players SET coins = coins + $2, updated_at = NOW() WHERE user_id = $1",
                        int(member["user_id"]), share + (remainder if index == 0 else 0)
                    )
                await connection.execute(
                    """UPDATE game_tournaments SET status = 'finished',
                       winner_family_id = $2, finished_at = NOW() WHERE id = $1""",
                    tournament_id, winner_family_id
                )
                return "ok", prize

    async def get_game_tournaments(self, limit: int = 10) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            """SELECT t.id, t.name, t.prize_coins, t.status, t.winner_family_id,
                      f.name AS winner_name, COUNT(tf.family_id)::int AS family_count,
                      t.organizer_id
               FROM game_tournaments t
               LEFT JOIN game_families f ON f.id = t.winner_family_id
               LEFT JOIN game_tournament_families tf ON tf.tournament_id = t.id
               GROUP BY t.id, f.name
               ORDER BY (t.status = 'open') DESC, t.created_at DESC LIMIT $1""",
            max(1, min(int(limit), 20))
        )


    async def signup_city_event(self, user_id: int, username: str, event_code: str) -> str:
        allowed = {"fair", "open_day", "cleanup"}
        if event_code not in allowed:
            return "missing"
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """INSERT INTO game_players (user_id, username) VALUES ($1, $2)
                       ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username""",
                    user_id, username[:64]
                )
                result = await connection.execute(
                    """INSERT INTO game_city_event_signups (event_code, user_id, username)
                       VALUES ($1, $2, $3) ON CONFLICT DO NOTHING""",
                    event_code, user_id, username[:64]
                )
                return "joined" if result.endswith("1") else "already"

    async def leave_city_event(self, user_id: int, event_code: str) -> str:
        if event_code not in {"fair", "open_day", "cleanup"}:
            return "missing"
        result = await self._require_pool().execute(
            "DELETE FROM game_city_event_signups WHERE event_code = $1 AND user_id = $2",
            event_code, user_id
        )
        return "left" if result.endswith("1") else "not_joined"

    async def get_city_event_signups(self, event_code: str) -> list[asyncpg.Record]:
        if event_code not in {"fair", "open_day", "cleanup"}:
            return []
        return await self._require_pool().fetch(
            """SELECT user_id, username FROM game_city_event_signups
               WHERE event_code = $1 ORDER BY signed_up_at ASC LIMIT 100""",
            event_code
        )

    async def get_user_city_event_signups(self, user_id: int) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            """SELECT event_code FROM game_city_event_signups
               WHERE user_id = $1 ORDER BY signed_up_at ASC""",
            user_id
        )


    async def claim_game_faction_leadership(self, user_id: int) -> tuple[bool, str]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                membership = await connection.fetchrow(
                    "SELECT faction_id FROM game_faction_members WHERE user_id = $1 FOR UPDATE",
                    user_id,
                )
                if membership is None:
                    return False, "Сначала вступи во фракцию."
                faction_id = membership["faction_id"]
                leader = await connection.fetchval(
                    "UPDATE game_factions SET leader_id = $1 WHERE id = $2 AND leader_id IS NULL RETURNING id",
                    user_id, faction_id,
                )
                if leader is None:
                    return False, "У этой фракции уже есть лидер."
                await connection.execute(
                    "UPDATE game_faction_members SET rank_name = 'Лидер' WHERE faction_id = $1 AND user_id = $2",
                    faction_id, user_id,
                )
                return True, "Ты назначен лидером фракции."

    async def get_game_faction_roster(self, user_id: int) -> tuple[asyncpg.Record | None, list[asyncpg.Record]]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            faction = await connection.fetchrow(
                """SELECT f.id, f.name, f.leader_id FROM game_factions f
                   JOIN game_faction_members m ON m.faction_id = f.id
                   WHERE m.user_id = $1""", user_id
            )
            if faction is None:
                return None, []
            members = await connection.fetch(
                """SELECT m.user_id, m.rank_name, p.username
                   FROM game_faction_members m JOIN game_players p ON p.user_id = m.user_id
                   WHERE m.faction_id = $1
                   ORDER BY CASE m.rank_name
                     WHEN 'Лидер' THEN 0 WHEN 'Заместитель' THEN 1
                     WHEN 'Старший' THEN 2 WHEN 'Сотрудник' THEN 3 ELSE 4 END,
                     m.joined_at ASC""",
                faction["id"]
            )
            return faction, members

    async def change_game_faction_rank(self, actor_id: int, target_id: int, direction: int) -> tuple[bool, str]:
        ranks = ["Рекрут", "Сотрудник", "Старший", "Заместитель", "Лидер"]
        if direction not in (-1, 1) or actor_id == target_id:
            return False, "Некорректная цель повышения или понижения."
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                actor = await connection.fetchrow(
                    """SELECT m.faction_id, f.leader_id FROM game_faction_members m
                       JOIN game_factions f ON f.id = m.faction_id
                       WHERE m.user_id = $1 FOR UPDATE OF f""", actor_id
                )
                if actor is None or actor["leader_id"] != actor_id:
                    return False, "Изменять ранги может только лидер фракции."
                target = await connection.fetchrow(
                    "SELECT rank_name FROM game_faction_members WHERE faction_id = $1 AND user_id = $2 FOR UPDATE",
                    actor["faction_id"], target_id
                )
                if target is None:
                    return False, "Игрок не состоит в твоей фракции."
                try:
                    index = ranks.index(target["rank_name"])
                except ValueError:
                    index = 0
                next_index = index + direction
                if next_index < 0 or next_index >= len(ranks) - 1:
                    return False, "Нельзя изменить ранг выше или ниже допустимого уровня."
                await connection.execute(
                    "UPDATE game_faction_members SET rank_name = $1 WHERE faction_id = $2 AND user_id = $3",
                    ranks[next_index], actor["faction_id"], target_id
                )
                return True, f"Новый ранг игрока: {ranks[next_index]}."

    async def remove_game_faction_member(self, actor_id: int, target_id: int) -> tuple[bool, str]:
        if actor_id == target_id:
            return False, "Лидер не может исключить самого себя."
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                actor = await connection.fetchrow(
                    """SELECT m.faction_id, f.leader_id FROM game_faction_members m
                       JOIN game_factions f ON f.id = m.faction_id
                       WHERE m.user_id = $1 FOR UPDATE OF f""", actor_id
                )
                if actor is None or actor["leader_id"] != actor_id:
                    return False, "Исключать участников может только лидер фракции."
                result = await connection.execute(
                    "DELETE FROM game_faction_members WHERE faction_id = $1 AND user_id = $2",
                    actor["faction_id"], target_id
                )
                return (True, "Участник исключён из фракции.") if result.endswith("1") else (False, "Игрок не найден во фракции.")

    async def transfer_game_faction_leadership(self, actor_id: int, target_id: int) -> tuple[bool, str]:
        if actor_id == target_id:
            return False, "Нельзя передать лидерство самому себе."
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                actor = await connection.fetchrow(
                    """SELECT faction_id FROM game_faction_members
                       WHERE user_id = $1 FOR UPDATE""", actor_id
                )
                if actor is None:
                    return False, "Ты не состоишь во фракции."
                faction_id = actor["faction_id"]
                faction = await connection.fetchrow(
                    "SELECT leader_id FROM game_factions WHERE id = $1 FOR UPDATE", faction_id
                )
                if faction is None or faction["leader_id"] != actor_id:
                    return False, "Передать лидерство может только действующий лидер."
                target = await connection.fetchrow(
                    "SELECT user_id FROM game_faction_members WHERE faction_id = $1 AND user_id = $2 FOR UPDATE",
                    faction_id, target_id
                )
                if target is None:
                    return False, "Новый лидер должен состоять в твоей фракции."
                await connection.execute(
                    "UPDATE game_faction_members SET rank_name = 'Заместитель' WHERE faction_id = $1 AND user_id = $2",
                    faction_id, actor_id
                )
                await connection.execute(
                    "UPDATE game_faction_members SET rank_name = 'Лидер' WHERE faction_id = $1 AND user_id = $2",
                    faction_id, target_id
                )
                await connection.execute(
                    "UPDATE game_factions SET leader_id = $1 WHERE id = $2", target_id, faction_id
                )
                return True, "Лидерство успешно передано."


    async def list_government_departments(self) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            """SELECT d.id, d.name, d.description, d.base_salary,
                      COUNT(e.user_id)::int AS employees
               FROM game_government_departments d
               LEFT JOIN game_government_employees e ON e.department_id = d.id
               GROUP BY d.id ORDER BY d.id"""
        )

    async def join_government_department(self, user_id: int, username: str, department_id: int) -> tuple[bool, str]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """INSERT INTO game_players (user_id, username) VALUES ($1, $2)
                       ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username""",
                    user_id, username[:64]
                )
                is_civil_servant = await connection.fetchval(
                    """SELECT EXISTS (
                        SELECT 1 FROM game_faction_members m
                        JOIN game_factions f ON f.id = m.faction_id
                        WHERE m.user_id = $1 AND f.name = 'Правительство Москвы'
                    )""", user_id
                )
                if not is_civil_servant:
                    return False, "Для устройства сначала вступи во фракцию «Правительство Москвы»."
                department = await connection.fetchrow(
                    "SELECT id, name FROM game_government_departments WHERE id = $1", department_id
                )
                if department is None:
                    return False, "Такого отдела нет. Используй /gov departments."
                current = await connection.fetchval(
                    "SELECT department_id FROM game_government_employees WHERE user_id = $1", user_id
                )
                if current is not None:
                    return False, "Ты уже работаешь в государственном отделе."
                await connection.execute(
                    """INSERT INTO game_government_employees (user_id, department_id)
                       VALUES ($1, $2)""", user_id, department_id
                )
                return True, f"Ты принят в отдел «{department['name']}»."

    async def leave_government_department(self, user_id: int) -> bool:
        result = await self._require_pool().execute(
            "DELETE FROM game_government_employees WHERE user_id = $1", user_id
        )
        return result.endswith("1")

    async def get_government_employee(self, user_id: int) -> asyncpg.Record | None:
        return await self._require_pool().fetchrow(
            """SELECT e.user_id, e.position, e.hired_at, e.last_salary_at,
                      d.id AS department_id, d.name AS department_name,
                      d.base_salary, p.username
               FROM game_government_employees e
               JOIN game_government_departments d ON d.id = e.department_id
               JOIN game_players p ON p.user_id = e.user_id
               WHERE e.user_id = $1""", user_id
        )

    async def get_government_roster(self, department_id: int) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            """SELECT e.user_id, e.position, p.username
               FROM game_government_employees e
               JOIN game_players p ON p.user_id = e.user_id
               WHERE e.department_id = $1
               ORDER BY CASE e.position WHEN 'Начальник отдела' THEN 0 ELSE 1 END,
                        e.hired_at LIMIT 100""", department_id
        )

    async def assign_government_task(self, actor_id: int, target_id: int, title: str, reward: int) -> tuple[bool, str]:
        if not 1 <= reward <= 500:
            return False, "Награда должна быть от 1 до 500 монет."
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                actor = await connection.fetchrow(
                    """SELECT department_id, position FROM game_government_employees
                       WHERE user_id = $1 FOR UPDATE""", actor_id
                )
                if actor is None or actor["position"] != "Начальник отдела":
                    return False, "Назначать поручения может только начальник отдела."
                target = await connection.fetchval(
                    """SELECT 1 FROM game_government_employees
                       WHERE user_id = $1 AND department_id = $2""", target_id, actor["department_id"]
                )
                if not target:
                    return False, "Сотрудник не найден в твоём отделе."
                task_id = await connection.fetchval(
                    """INSERT INTO game_government_tasks
                       (department_id, assigned_to, title, reward_coins)
                       VALUES ($1, $2, $3, $4) RETURNING id""",
                    actor["department_id"], target_id, title[:120], reward
                )
                return True, f"Поручение №{task_id} назначено."

    async def get_government_tasks(self, user_id: int) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            """SELECT id, title, reward_coins, status FROM game_government_tasks
               WHERE assigned_to = $1 ORDER BY created_at DESC LIMIT 20""", user_id
        )

    async def complete_government_task(self, user_id: int, task_id: int) -> tuple[bool, str]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                task = await connection.fetchrow(
                    """SELECT id, reward_coins FROM game_government_tasks
                       WHERE id = $1 AND assigned_to = $2 AND status = 'open' FOR UPDATE""",
                    task_id, user_id
                )
                if task is None:
                    return False, "Открытое поручение с таким номером не найдено."
                await connection.execute(
                    "UPDATE game_government_tasks SET status = 'completed', completed_at = NOW() WHERE id = $1",
                    task_id
                )
                await connection.execute(
                    "UPDATE game_players SET coins = coins + $1, updated_at = NOW() WHERE user_id = $2",
                    task["reward_coins"], user_id
                )
                return True, f"Поручение выполнено. Начислено {task['reward_coins']} монет."

    async def claim_government_salary(self, user_id: int) -> tuple[bool, str]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                employee = await connection.fetchrow(
                    """SELECT e.position, e.last_salary_at, d.base_salary
                       FROM game_government_employees e
                       JOIN game_government_departments d ON d.id = e.department_id
                       WHERE e.user_id = $1 FOR UPDATE OF e""", user_id
                )
                if employee is None:
                    return False, "Сначала устройся в государственный отдел через /gov join ID."
                if employee["last_salary_at"] is not None:
                    available = await connection.fetchval(
                        "SELECT $1::timestamptz + INTERVAL '24 hours' <= NOW()",
                        employee["last_salary_at"]
                    )
                    if not available:
                        return False, "Зарплату можно получать раз в 24 часа."
                salary = employee["base_salary"] + (100 if employee["position"] == "Начальник отдела" else 0)
                await connection.execute(
                    "UPDATE game_players SET coins = coins + $1, updated_at = NOW() WHERE user_id = $2",
                    salary, user_id
                )
                await connection.execute(
                    "UPDATE game_government_employees SET last_salary_at = NOW() WHERE user_id = $1",
                    user_id
                )
                return True, f"Зарплата начислена: {salary} игровых монет."


database = Database()
