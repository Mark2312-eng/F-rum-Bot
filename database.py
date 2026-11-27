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
            # Explicitly remove the legacy gameplay schema after the owner's approval.
            # CASCADE removes only dependencies attached to these named gameplay tables.
            await connection.execute("""
                DROP TABLE IF EXISTS game_players,
                    game_achievements,
                    game_families,
                    game_family_members,
                    game_government_departments,
                    game_government_employees,
                    game_government_tasks,
                    game_factions,
                    game_faction_members,
                    game_medical_centers,
                    game_medical_employees,
                    game_medical_missions,
                    game_medical_completions,
                    game_education_institutions,
                    game_education_students,
                    game_education_groups,
                    game_education_courses,
                    game_education_completions,
                    game_service_profiles,
                    game_service_missions,
                    game_service_completions,
                    game_inventory,
                    game_properties,
                    game_jobs,
                    game_employment,
                    game_transport_routes,
                    game_transport_stops,
                    game_transport_route_stops,
                    game_transport_tickets,
                    game_taxi_orders,
                    game_taxi_ratings,
                    game_transport_rides,
                    game_shop_items,
                    game_property_catalog,
                    game_vehicle_catalog,
                    game_vehicles,
                    game_events,
                    game_quest_progress,
                    game_quest_catalog,
                    game_city_event_signups,
                    game_tournaments,
                    game_tournament_families CASCADE;
            """)
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
                CREATE TABLE IF NOT EXISTS moderation_reports (
                    id BIGSERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, reporter_id BIGINT NOT NULL,
                    target_id BIGINT NOT NULL, reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), closed_by BIGINT, closed_at TIMESTAMPTZ
                );
                CREATE INDEX IF NOT EXISTS moderation_reports_open_idx
                    ON moderation_reports (chat_id, created_at DESC) WHERE status = 'open';
                CREATE TABLE IF NOT EXISTS global_blacklist (
                    user_id BIGINT PRIMARY KEY, added_by BIGINT NOT NULL, reason TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS chat_nicknames (
                    chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
                    nickname TEXT NOT NULL CHECK (char_length(nickname) BETWEEN 1 AND 32),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), PRIMARY KEY (chat_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS chat_moderators (
                    chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL, assigned_by BIGINT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), PRIMARY KEY (chat_id, user_id)
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


    async def get_warning_count(self, chat_id: int, user_id: int) -> int:
        pool = self._require_pool()
        value = await pool.fetchval(
            "SELECT warning_count FROM moderation_warnings WHERE chat_id = $1 AND user_id = $2",
            chat_id, user_id,
        )
        return int(value or 0)

    async def get_moderation_stats(self, chat_id: int) -> list[asyncpg.Record]:
        pool = self._require_pool()
        return await pool.fetch(
            """SELECT action, COUNT(*) AS total
               FROM moderation_events
               WHERE chat_id = $1 AND created_at >= NOW() - INTERVAL '7 days'
               GROUP BY action ORDER BY total DESC, action ASC""",
            chat_id,
        )



    async def create_report(self, chat_id: int, reporter_id: int, target_id: int, reason: str) -> int:
        pool = self._require_pool()
        return int(await pool.fetchval(
            """INSERT INTO moderation_reports (chat_id, reporter_id, target_id, reason)
               VALUES ($1, $2, $3, $4) RETURNING id""", chat_id, reporter_id, target_id, reason[:500]))

    async def get_open_reports(self, chat_id: int) -> list[asyncpg.Record]:
        pool = self._require_pool()
        return await pool.fetch(
            """SELECT id, reporter_id, target_id, reason, created_at FROM moderation_reports
               WHERE chat_id = $1 AND status = 'open' ORDER BY created_at ASC LIMIT 30""", chat_id)

    async def close_report(self, chat_id: int, report_id: int, actor_id: int) -> bool:
        pool = self._require_pool()
        result = await pool.execute(
            """UPDATE moderation_reports SET status = 'closed', closed_by = $3, closed_at = NOW()
               WHERE chat_id = $1 AND id = $2 AND status = 'open'""", chat_id, report_id, actor_id)
        return result.endswith(" 1")

    async def add_blacklist(self, user_id: int, actor_id: int, reason: str) -> None:
        pool = self._require_pool()
        await pool.execute(
            """INSERT INTO global_blacklist (user_id, added_by, reason) VALUES ($1, $2, $3)
               ON CONFLICT (user_id) DO UPDATE SET added_by = EXCLUDED.added_by,
               reason = EXCLUDED.reason, created_at = NOW()""", user_id, actor_id, reason[:300])

    async def remove_blacklist(self, user_id: int) -> bool:
        pool = self._require_pool()
        result = await pool.execute("DELETE FROM global_blacklist WHERE user_id = $1", user_id)
        return result.endswith(" 1")

    async def get_blacklist(self) -> list[asyncpg.Record]:
        pool = self._require_pool()
        return await pool.fetch("SELECT user_id, reason FROM global_blacklist ORDER BY created_at DESC LIMIT 100")

    async def is_blacklisted(self, user_id: int) -> bool:
        pool = self._require_pool()
        return bool(await pool.fetchval("SELECT EXISTS(SELECT 1 FROM global_blacklist WHERE user_id = $1)", user_id))

    async def set_nickname(self, chat_id: int, user_id: int, nickname: str) -> None:
        pool = self._require_pool()
        await pool.execute(
            """INSERT INTO chat_nicknames (chat_id, user_id, nickname) VALUES ($1, $2, $3)
               ON CONFLICT (chat_id, user_id) DO UPDATE SET nickname = EXCLUDED.nickname, updated_at = NOW()""",
            chat_id, user_id, nickname[:32])

    async def get_nickname(self, chat_id: int, user_id: int) -> str | None:
        pool = self._require_pool()
        return await pool.fetchval("SELECT nickname FROM chat_nicknames WHERE chat_id = $1 AND user_id = $2", chat_id, user_id)

    async def set_custom_moderator(self, chat_id: int, user_id: int, actor_id: int) -> None:
        pool = self._require_pool()
        await pool.execute(
            """INSERT INTO chat_moderators (chat_id, user_id, assigned_by) VALUES ($1, $2, $3)
               ON CONFLICT (chat_id, user_id) DO NOTHING""", chat_id, user_id, actor_id)

    async def remove_custom_moderator(self, chat_id: int, user_id: int) -> bool:
        pool = self._require_pool()
        result = await pool.execute("DELETE FROM chat_moderators WHERE chat_id = $1 AND user_id = $2", chat_id, user_id)
        return result.endswith(" 1")

    async def list_custom_moderators(self, chat_id: int) -> list[asyncpg.Record]:
        pool = self._require_pool()
        return await pool.fetch("SELECT user_id FROM chat_moderators WHERE chat_id = $1 ORDER BY created_at", chat_id)

    async def is_custom_moderator(self, chat_id: int, user_id: int) -> bool:
        pool = self._require_pool()
        return bool(await pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM chat_moderators WHERE chat_id = $1 AND user_id = $2)", chat_id, user_id))

database = Database()
