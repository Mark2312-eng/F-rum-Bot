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
                CREATE TABLE IF NOT EXISTS chat_role_definitions (
                    chat_id BIGINT NOT NULL REFERENCES registered_chats(chat_id) ON DELETE CASCADE,
                    role_key TEXT NOT NULL,
                    title TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 32),
                    priority SMALLINT NOT NULL CHECK (priority BETWEEN 1 AND 99),
                    is_system BOOLEAN NOT NULL DEFAULT FALSE,
                    created_by BIGINT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (chat_id, role_key),
                    UNIQUE (chat_id, title)
                );
                CREATE TABLE IF NOT EXISTS chat_member_roles (
                    chat_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    role_key TEXT NOT NULL,
                    assigned_by BIGINT NOT NULL,
                    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (chat_id, user_id),
                    FOREIGN KEY (chat_id, role_key)
                        REFERENCES chat_role_definitions(chat_id, role_key) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS chat_member_roles_role_idx
                    ON chat_member_roles (chat_id, role_key);
                CREATE TABLE IF NOT EXISTS chat_role_immunity (
                    chat_id BIGINT NOT NULL REFERENCES registered_chats(chat_id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL,
                    enabled_by BIGINT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (chat_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS chat_command_permissions (
                    chat_id BIGINT NOT NULL REFERENCES registered_chats(chat_id) ON DELETE CASCADE,
                    command_name TEXT NOT NULL,
                    min_priority SMALLINT NOT NULL CHECK (min_priority BETWEEN 0 AND 100),
                    updated_by BIGINT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (chat_id, command_name)
                );
                CREATE TABLE IF NOT EXISTS chat_role_audit (
                    id BIGSERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    actor_id BIGINT NOT NULL,
                    target_id BIGINT,
                    action TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS chat_role_audit_recent_idx
                    ON chat_role_audit (chat_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS system_staff (
                    user_id BIGINT PRIMARY KEY,
                    role_key TEXT NOT NULL,
                    assigned_by BIGINT NOT NULL,
                    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS system_staff_role_idx ON system_staff (role_key);
                CREATE TABLE IF NOT EXISTS system_staff_log (
                    id BIGSERIAL PRIMARY KEY,
                    actor_id BIGINT NOT NULL,
                    target_id BIGINT NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS system_staff_log_created_idx
                    ON system_staff_log (created_at DESC);

                CREATE TABLE IF NOT EXISTS moderation_tests (
                    id BIGSERIAL PRIMARY KEY,
                    title TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 120),
                    creator_id BIGINT NOT NULL,
                    chat_id BIGINT NOT NULL REFERENCES registered_chats(chat_id) ON DELETE CASCADE,
                    role_key TEXT NOT NULL CHECK (role_key IN ('moderator')),
                    pass_score INTEGER NOT NULL CHECK (pass_score BETWEEN 1 AND 100),
                    cooldown_days INTEGER NOT NULL DEFAULT 7 CHECK (cooldown_days BETWEEN 0 AND 90),
                    time_limit_minutes INTEGER NOT NULL DEFAULT 30 CHECK (time_limit_minutes BETWEEN 1 AND 240),
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS moderation_tests_creator_idx
                    ON moderation_tests (creator_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS moderation_test_questions (
                    id BIGSERIAL PRIMARY KEY,
                    test_id BIGINT NOT NULL REFERENCES moderation_tests(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL CHECK (position > 0),
                    prompt TEXT NOT NULL CHECK (char_length(prompt) BETWEEN 1 AND 1000),
                    options JSONB NOT NULL,
                    correct_option INTEGER NOT NULL DEFAULT 0 CHECK (correct_option >= 0),
                    UNIQUE (test_id, position)
                );
                CREATE TABLE IF NOT EXISTS moderation_test_invites (
                    token_hash TEXT PRIMARY KEY,
                    test_id BIGINT NOT NULL REFERENCES moderation_tests(id) ON DELETE CASCADE,
                    target_user_id BIGINT NOT NULL,
                    issued_by BIGINT NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    used_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS moderation_test_sessions (
                    id BIGSERIAL PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE REFERENCES moderation_test_invites(token_hash) ON DELETE CASCADE,
                    test_id BIGINT NOT NULL REFERENCES moderation_tests(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL,
                    current_position INTEGER NOT NULL DEFAULT 1 CHECK (current_position > 0),
                    score INTEGER NOT NULL DEFAULT 0 CHECK (score >= 0),
                    expires_at TIMESTAMPTZ NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'passed', 'failed', 'expired')),
                    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at TIMESTAMPTZ
                );
                CREATE INDEX IF NOT EXISTS moderation_test_sessions_user_idx
                    ON moderation_test_sessions (user_id, started_at DESC);
                CREATE TABLE IF NOT EXISTS moderation_test_results (
                    id BIGSERIAL PRIMARY KEY,
                    test_id BIGINT NOT NULL REFERENCES moderation_tests(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL,
                    score_percent INTEGER NOT NULL CHECK (score_percent BETWEEN 0 AND 100),
                    passed BOOLEAN NOT NULL,
                    role_assigned TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS moderation_test_results_test_idx
                    ON moderation_test_results (test_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS moderation_test_cooldowns (
                    test_id BIGINT NOT NULL REFERENCES moderation_tests(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL,
                    available_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (test_id, user_id)
                );
            """)
        await self.ensure_chat_roles()

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
        await self.ensure_chat_roles()

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
        return await self.get_chat_member_priority(chat_id, user_id) >= 40


    async def get_system_role(self, user_id: int) -> str | None:
        pool = self._require_pool()
        return await pool.fetchval("SELECT role_key FROM system_staff WHERE user_id = $1", user_id)

    async def set_system_role(self, user_id: int, role_key: str, actor_id: int) -> None:
        pool = self._require_pool()
        await pool.execute(
            """INSERT INTO system_staff (user_id, role_key, assigned_by)
               VALUES ($1, $2, $3)
               ON CONFLICT (user_id) DO UPDATE SET role_key = EXCLUDED.role_key,
               assigned_by = EXCLUDED.assigned_by, assigned_at = NOW()""",
            user_id, role_key, actor_id,
        )

    async def remove_system_role(self, user_id: int) -> bool:
        pool = self._require_pool()
        result = await pool.execute("DELETE FROM system_staff WHERE user_id = $1", user_id)
        return result.endswith(" 1")

    async def list_system_staff(self) -> list[asyncpg.Record]:
        pool = self._require_pool()
        return await pool.fetch(
            "SELECT user_id, role_key, assigned_by, assigned_at FROM system_staff ORDER BY assigned_at"
        )

    async def add_system_staff_log(self, actor_id: int, target_id: int, action: str, details: str = "") -> None:
        pool = self._require_pool()
        await pool.execute(
            """INSERT INTO system_staff_log (actor_id, target_id, action, details)
               VALUES ($1, $2, $3, $4)""",
            actor_id, target_id, action[:40], details[:160],
        )

    async def get_system_staff_log(self, limit: int = 15) -> list[asyncpg.Record]:
        pool = self._require_pool()
        safe_limit = max(1, min(int(limit), 50))
        return await pool.fetch(
            """SELECT actor_id, target_id, action, details, created_at
               FROM system_staff_log ORDER BY created_at DESC, id DESC LIMIT $1""",
            safe_limit,
        )


    async def assign_system_role_guarded(
        self, user_id: int, role_key: str, actor_id: int, owner_id: int,
        role_ranks: dict[str, int],
    ) -> bool:
        """Atomically validate staff hierarchy, assign a role and write its audit event."""
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock(726301)")
                actor_role = "owner" if actor_id == owner_id else await connection.fetchval(
                    "SELECT role_key FROM system_staff WHERE user_id = $1", actor_id
                )
                target_role = "owner" if user_id == owner_id else await connection.fetchval(
                    "SELECT role_key FROM system_staff WHERE user_id = $1", user_id
                )
                actor_rank = 100 if actor_role == "owner" else role_ranks.get(actor_role, 0)
                target_rank = 100 if target_role == "owner" else role_ranks.get(target_role, 0)
                requested_rank = role_ranks.get(role_key, 0)
                if user_id == actor_id or user_id == owner_id or actor_rank <= max(target_rank, requested_rank):
                    return False
                await connection.execute(
                    """INSERT INTO system_staff (user_id, role_key, assigned_by)
                       VALUES ($1, $2, $3)
                       ON CONFLICT (user_id) DO UPDATE SET role_key = EXCLUDED.role_key,
                       assigned_by = EXCLUDED.assigned_by, assigned_at = NOW()""",
                    user_id, role_key, actor_id,
                )
                await connection.execute(
                    """INSERT INTO system_staff_log (actor_id, target_id, action, details)
                       VALUES ($1, $2, 'set_role', $3)""",
                    actor_id, user_id, role_key,
                )
                return True

    async def remove_system_role_guarded(
        self, user_id: int, actor_id: int, owner_id: int,
        role_ranks: dict[str, int],
    ) -> bool:
        """Atomically enforce hierarchy when removing a staff role and audit it."""
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock(726301)")
                actor_role = "owner" if actor_id == owner_id else await connection.fetchval(
                    "SELECT role_key FROM system_staff WHERE user_id = $1", actor_id
                )
                target_role = "owner" if user_id == owner_id else await connection.fetchval(
                    "SELECT role_key FROM system_staff WHERE user_id = $1", user_id
                )
                actor_rank = 100 if actor_role == "owner" else role_ranks.get(actor_role, 0)
                target_rank = 100 if target_role == "owner" else role_ranks.get(target_role, 0)
                if user_id in {actor_id, owner_id} or not target_role or actor_rank <= target_rank:
                    return False
                result = await connection.execute(
                    "DELETE FROM system_staff WHERE user_id = $1", user_id
                )
                if not result.endswith(" 1"):
                    return False
                await connection.execute(
                    """INSERT INTO system_staff_log (actor_id, target_id, action, details)
                       VALUES ($1, $2, 'remove_role', '')""",
                    actor_id, user_id,
                )
                return True



    async def ensure_chat_roles(self) -> None:
        """Seed default per-chat roles and migrate legacy delegated moderators."""
        pool = self._require_pool()
        defaults = [
            ("chief_admin", "Главный администратор", 80),
            ("admin", "Администратор", 60),
            ("moderator", "Модератор", 40),
            ("helper", "Помощник", 20),
        ]
        async with pool.acquire() as connection:
            async with connection.transaction():
                for key, title, priority in defaults:
                    await connection.execute(
                        """INSERT INTO chat_role_definitions
                           (chat_id, role_key, title, priority, is_system, created_by)
                           SELECT chat_id, $1, $2, $3, TRUE, connected_by
                           FROM registered_chats
                           ON CONFLICT (chat_id, role_key) DO NOTHING""",
                        key, title, priority,
                    )
                await connection.execute(
                    """INSERT INTO chat_member_roles (chat_id, user_id, role_key, assigned_by)
                       SELECT m.chat_id, m.user_id, 'moderator', m.assigned_by
                       FROM chat_moderators m
                       JOIN chat_role_definitions r
                         ON r.chat_id = m.chat_id AND r.role_key = 'moderator'
                       ON CONFLICT (chat_id, user_id) DO NOTHING"""
                )

    async def get_chat_role_definitions(self, chat_id: int):
        pool = self._require_pool()
        return await pool.fetch(
            """SELECT role_key, title, priority, is_system
               FROM chat_role_definitions WHERE chat_id = $1
               ORDER BY priority DESC, title""", chat_id
        )

    async def get_chat_member_role(self, chat_id: int, user_id: int):
        pool = self._require_pool()
        return await pool.fetchrow(
            """SELECT r.role_key, r.title, r.priority
               FROM chat_member_roles m JOIN chat_role_definitions r
                 ON r.chat_id = m.chat_id AND r.role_key = m.role_key
               WHERE m.chat_id = $1 AND m.user_id = $2""", chat_id, user_id
        )

    async def get_chat_member_priority(self, chat_id: int, user_id: int) -> int:
        pool = self._require_pool()
        value = await pool.fetchval(
            """SELECT MAX(priority) FROM (
                 SELECT r.priority FROM chat_member_roles m
                 JOIN chat_role_definitions r ON r.chat_id = m.chat_id AND r.role_key = m.role_key
                 WHERE m.chat_id = $1 AND m.user_id = $2
                 UNION ALL
                 SELECT 40 WHERE EXISTS (
                   SELECT 1 FROM chat_moderators WHERE chat_id = $1 AND user_id = $2
                 )
               ) p""", chat_id, user_id
        )
        return int(value or 0)

    async def is_chat_member_immune(self, chat_id: int, user_id: int) -> bool:
        pool = self._require_pool()
        return bool(await pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM chat_role_immunity WHERE chat_id = $1 AND user_id = $2)",
            chat_id, user_id,
        ))

    async def create_chat_role(
        self, chat_id: int, role_key: str, title: str, priority: int,
        actor_id: int, actor_priority: int,
    ) -> bool:
        if actor_priority < 80 or not 1 <= priority <= 79:
            return False
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock($1)", chat_id)
                exists = await connection.fetchval(
                    """SELECT EXISTS(SELECT 1 FROM chat_role_definitions
                       WHERE chat_id = $1 AND (role_key = $2 OR lower(title) = lower($3)))""",
                    chat_id, role_key, title,
                )
                if exists:
                    return False
                await connection.execute(
                    """INSERT INTO chat_role_definitions
                       (chat_id, role_key, title, priority, created_by)
                       VALUES ($1, $2, $3, $4, $5)""",
                    chat_id, role_key, title, priority, actor_id,
                )
                await connection.execute(
                    """INSERT INTO chat_role_audit (chat_id, actor_id, action, details)
                       VALUES ($1, $2, 'create_role', $3)""",
                    chat_id, actor_id, f"{title}:{priority}",
                )
                return True

    async def delete_chat_role(
        self, chat_id: int, role_key: str, actor_id: int, actor_priority: int,
    ) -> bool:
        if actor_priority < 80:
            return False
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock($1)", chat_id)
                role = await connection.fetchrow(
                    """SELECT title, priority, is_system FROM chat_role_definitions
                       WHERE chat_id = $1 AND role_key = $2 FOR UPDATE""",
                    chat_id, role_key,
                )
                if not role or role["is_system"]:
                    return False
                if role["priority"] >= actor_priority:
                    return False
                assigned = await connection.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM chat_member_roles WHERE chat_id = $1 AND role_key = $2)",
                    chat_id, role_key,
                )
                if assigned:
                    return False
                await connection.execute(
                    "DELETE FROM chat_role_definitions WHERE chat_id = $1 AND role_key = $2",
                    chat_id, role_key,
                )
                await connection.execute(
                    """INSERT INTO chat_role_audit (chat_id, actor_id, action, details)
                       VALUES ($1, $2, 'delete_role', $3)""",
                    chat_id, actor_id, f"{role_key}:{role['title']}",
                )
                return True

    async def assign_chat_role_guarded(
        self, chat_id: int, user_id: int, role_key: str, actor_id: int,
        actor_priority: int,
    ) -> bool:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock($1)", chat_id)
                role = await connection.fetchrow(
                    """SELECT priority FROM chat_role_definitions
                       WHERE chat_id = $1 AND role_key = $2""", chat_id, role_key,
                )
                if not role or user_id == actor_id:
                    return False
                target_priority = await connection.fetchval(
                    """SELECT MAX(priority) FROM (
                         SELECT r.priority FROM chat_member_roles m
                         JOIN chat_role_definitions r ON r.chat_id = m.chat_id AND r.role_key = m.role_key
                         WHERE m.chat_id = $1 AND m.user_id = $2
                         UNION ALL
                         SELECT 40 WHERE EXISTS (
                           SELECT 1 FROM chat_moderators WHERE chat_id = $1 AND user_id = $2
                         )
                       ) p""", chat_id, user_id,
                ) or 0
                immune = await connection.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM chat_role_immunity WHERE chat_id = $1 AND user_id = $2)",
                    chat_id, user_id,
                )
                if immune or actor_priority <= max(int(target_priority), int(role["priority"])):
                    return False
                await connection.execute(
                    """INSERT INTO chat_member_roles (chat_id, user_id, role_key, assigned_by)
                       VALUES ($1, $2, $3, $4)
                       ON CONFLICT (chat_id, user_id) DO UPDATE SET role_key = EXCLUDED.role_key,
                       assigned_by = EXCLUDED.assigned_by, assigned_at = NOW()""",
                    chat_id, user_id, role_key, actor_id,
                )
                await connection.execute(
                    "DELETE FROM chat_moderators WHERE chat_id = $1 AND user_id = $2",
                    chat_id, user_id,
                )
                await connection.execute(
                    """INSERT INTO chat_role_audit (chat_id, actor_id, target_id, action, details)
                       VALUES ($1, $2, $3, 'assign_role', $4)""",
                    chat_id, actor_id, user_id, role_key,
                )
                return True

    async def remove_chat_role_guarded(
        self, chat_id: int, user_id: int, actor_id: int, actor_priority: int,
    ) -> bool:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock($1)", chat_id)
                row = await connection.fetchrow(
                    """SELECT r.priority, m.role_key FROM chat_member_roles m
                       JOIN chat_role_definitions r ON r.chat_id = m.chat_id AND r.role_key = m.role_key
                       WHERE m.chat_id = $1 AND m.user_id = $2 FOR UPDATE OF m""",
                    chat_id, user_id,
                )
                if not row or user_id == actor_id or actor_priority <= row["priority"]:
                    return False
                await connection.execute(
                    "DELETE FROM chat_member_roles WHERE chat_id = $1 AND user_id = $2",
                    chat_id, user_id,
                )
                await connection.execute(
                    """INSERT INTO chat_role_audit (chat_id, actor_id, target_id, action, details)
                       VALUES ($1, $2, $3, 'remove_role', $4)""",
                    chat_id, actor_id, user_id, row["role_key"],
                )
                return True

    async def set_chat_immunity_guarded(
        self, chat_id: int, user_id: int, actor_id: int, actor_priority: int, enabled: bool,
    ) -> bool:
        if actor_priority < 80 or user_id == actor_id:
            return False
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock($1)", chat_id)
                target_priority = await connection.fetchval(
                    """SELECT MAX(priority) FROM (
                         SELECT r.priority FROM chat_member_roles m
                         JOIN chat_role_definitions r ON r.chat_id = m.chat_id AND r.role_key = m.role_key
                         WHERE m.chat_id = $1 AND m.user_id = $2
                         UNION ALL
                         SELECT 40 WHERE EXISTS (
                           SELECT 1 FROM chat_moderators WHERE chat_id = $1 AND user_id = $2
                         )
                       ) p""", chat_id, user_id,
                ) or 0
                if actor_priority <= int(target_priority):
                    return False
                if enabled:
                    await connection.execute(
                        """INSERT INTO chat_role_immunity (chat_id, user_id, enabled_by)
                           VALUES ($1, $2, $3) ON CONFLICT (chat_id, user_id)
                           DO UPDATE SET enabled_by = EXCLUDED.enabled_by, created_at = NOW()""",
                        chat_id, user_id, actor_id,
                    )
                else:
                    await connection.execute(
                        "DELETE FROM chat_role_immunity WHERE chat_id = $1 AND user_id = $2",
                        chat_id, user_id,
                    )
                await connection.execute(
                    """INSERT INTO chat_role_audit (chat_id, actor_id, target_id, action, details)
                       VALUES ($1, $2, $3, 'immunity', $4)""",
                    chat_id, actor_id, user_id, "on" if enabled else "off",
                )
                return True

    async def set_chat_command_priority(
        self, chat_id: int, command_name: str, min_priority: int, actor_id: int,
        actor_priority: int,
    ) -> bool:
        if actor_priority < 80 or not 0 <= min_priority <= 100 or min_priority > actor_priority:
            return False
        pool = self._require_pool()
        await pool.execute(
            """INSERT INTO chat_command_permissions
               (chat_id, command_name, min_priority, updated_by)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (chat_id, command_name) DO UPDATE SET
               min_priority = EXCLUDED.min_priority, updated_by = EXCLUDED.updated_by,
               updated_at = NOW()""",
            chat_id, command_name.lower(), min_priority, actor_id,
        )
        return True

    async def get_chat_command_priority(self, chat_id: int, command_name: str) -> int | None:
        pool = self._require_pool()
        value = await pool.fetchval(
            "SELECT min_priority FROM chat_command_permissions WHERE chat_id = $1 AND command_name = $2",
            chat_id, command_name.lower(),
        )
        return int(value) if value is not None else None


database = Database()
