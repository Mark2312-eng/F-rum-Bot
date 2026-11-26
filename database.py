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
                CREATE TABLE IF NOT EXISTS game_factions (
                    id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS game_faction_members (
                    faction_id BIGINT NOT NULL REFERENCES game_factions(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL REFERENCES game_players(user_id) ON DELETE CASCADE,
                    rank_name TEXT NOT NULL DEFAULT 'Новичок', joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (faction_id, user_id), UNIQUE (user_id)
                );
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



database = Database()
