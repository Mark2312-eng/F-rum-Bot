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
                    ('ФСБ', 'Государственная служба безопасности игрового мира.'),
                    ('МВД', 'Полиция и общественная служба игрового мира.'),
                    ('Городская больница', 'Медицинская организация игрового города.'),
                    ('Городское образование', 'Школы и университеты игрового города.')
                ON CONFLICT (name) DO NOTHING;
                CREATE TABLE IF NOT EXISTS game_medical_centers (
                    id BIGSERIAL PRIMARY KEY,
                    faction_id BIGINT NOT NULL REFERENCES game_factions(id) ON DELETE CASCADE,
                    name TEXT NOT NULL UNIQUE,
                    district TEXT NOT NULL,
                    UNIQUE (id, faction_id)
                );
                CREATE TABLE IF NOT EXISTS game_medical_employees (
                    user_id BIGINT PRIMARY KEY REFERENCES game_players(user_id) ON DELETE CASCADE,
                    faction_id BIGINT NOT NULL REFERENCES game_factions(id) ON DELETE CASCADE,
                    center_id BIGINT NOT NULL,
                    job_title TEXT NOT NULL DEFAULT 'Стажёр',
                    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    FOREIGN KEY (center_id, faction_id)
                        REFERENCES game_medical_centers(id, faction_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS game_medical_center_idx
                    ON game_medical_employees (center_id, job_title);
                CREATE TABLE IF NOT EXISTS game_medical_missions (
                    id BIGSERIAL PRIMARY KEY,
                    faction_id BIGINT NOT NULL REFERENCES game_factions(id) ON DELETE CASCADE,
                    code TEXT NOT NULL,
                    title TEXT NOT NULL,
                    reward_coins INTEGER NOT NULL CHECK (reward_coins > 0),
                    reward_xp INTEGER NOT NULL CHECK (reward_xp >= 0),
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    UNIQUE (faction_id, code)
                );
                CREATE TABLE IF NOT EXISTS game_medical_completions (
                    user_id BIGINT NOT NULL REFERENCES game_players(user_id) ON DELETE CASCADE,
                    mission_id BIGINT NOT NULL REFERENCES game_medical_missions(id) ON DELETE CASCADE,
                    completed_on DATE NOT NULL DEFAULT CURRENT_DATE,
                    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (user_id, mission_id, completed_on)
                );
                INSERT INTO game_medical_centers (faction_id, name, district)
                SELECT f.id, c.name, c.district
                FROM game_factions f
                CROSS JOIN (VALUES
                    ('Центральная городская больница', 'Центр'),
                    ('Северная клиника', 'Северный район'),
                    ('Станция городской медицины', 'Южный район')
                ) AS c(name, district)
                WHERE f.name = 'Городская больница'
                ON CONFLICT (name) DO NOTHING;
                INSERT INTO game_medical_missions (faction_id, code, title, reward_coins, reward_xp)
                SELECT f.id, m.code, m.title, m.reward_coins, m.reward_xp
                FROM game_factions f
                CROSS JOIN (VALUES
                    ('orientation', 'Пройти вводную экскурсию по игровой больнице', 40, 15),
                    ('records', 'Заполнить учебную карточку вымышленного пациента-NPC', 50, 20),
                    ('community', 'Принять участие в городском дне здоровья для NPC', 65, 25),
                    ('training', 'Посетить учебное занятие медицинского отдела', 55, 20)
                ) AS m(code, title, reward_coins, reward_xp)
                WHERE f.name = 'Городская больница'
                ON CONFLICT (faction_id, code) DO NOTHING;
                CREATE TABLE IF NOT EXISTS game_education_institutions (
                    id BIGSERIAL PRIMARY KEY,
                    faction_id BIGINT NOT NULL REFERENCES game_factions(id) ON DELETE CASCADE,
                    name TEXT NOT NULL UNIQUE,
                    institution_type TEXT NOT NULL,
                    district TEXT NOT NULL,
                    UNIQUE (id, faction_id)
                );
                CREATE TABLE IF NOT EXISTS game_education_students (
                    user_id BIGINT PRIMARY KEY REFERENCES game_players(user_id) ON DELETE CASCADE,
                    faction_id BIGINT NOT NULL REFERENCES game_factions(id) ON DELETE CASCADE,
                    institution_id BIGINT NOT NULL,
                    enrolled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    FOREIGN KEY (institution_id, faction_id)
                        REFERENCES game_education_institutions(id, faction_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS game_education_institution_idx
                    ON game_education_students (institution_id, enrolled_at);
                CREATE TABLE IF NOT EXISTS game_education_groups (
                    id BIGSERIAL PRIMARY KEY,
                    institution_id BIGINT NOT NULL REFERENCES game_education_institutions(id) ON DELETE CASCADE,
                    group_code TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    UNIQUE (institution_id, group_code)
                );
                ALTER TABLE game_education_students
                    ADD COLUMN IF NOT EXISTS group_id BIGINT
                    REFERENCES game_education_groups(id) ON DELETE SET NULL;
                INSERT INTO game_education_groups (institution_id, group_code, group_name)
                SELECT i.id, g.group_code, g.group_name
                FROM game_education_institutions i
                CROSS JOIN (VALUES
                    ('A-01', 'Учебная группа А-01'),
                    ('B-01', 'Учебная группа Б-01'),
                    ('C-01', 'Учебная группа В-01')
                ) AS g(group_code, group_name)
                ON CONFLICT (institution_id, group_code) DO NOTHING;
                CREATE TABLE IF NOT EXISTS game_education_courses (
                    id BIGSERIAL PRIMARY KEY,
                    faction_id BIGINT NOT NULL REFERENCES game_factions(id) ON DELETE CASCADE,
                    code TEXT NOT NULL,
                    title TEXT NOT NULL,
                    course_type TEXT NOT NULL CHECK (course_type IN ('lesson', 'exam')),
                    reward_coins INTEGER NOT NULL CHECK (reward_coins > 0),
                    reward_xp INTEGER NOT NULL CHECK (reward_xp >= 0),
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    UNIQUE (faction_id, code)
                );
                CREATE TABLE IF NOT EXISTS game_education_completions (
                    user_id BIGINT NOT NULL REFERENCES game_players(user_id) ON DELETE CASCADE,
                    course_id BIGINT NOT NULL REFERENCES game_education_courses(id) ON DELETE CASCADE,
                    completed_on DATE NOT NULL DEFAULT CURRENT_DATE,
                    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (user_id, course_id, completed_on)
                );
                INSERT INTO game_education_institutions (faction_id, name, institution_type, district)
                SELECT f.id, i.name, i.institution_type, i.district
                FROM game_factions f
                CROSS JOIN (VALUES
                    ('Средняя школа № 1', 'Школа', 'Центр'),
                    ('Городской технический колледж', 'Колледж', 'Северный район'),
                    ('Виртуальный городской университет', 'Университет', 'Центр')
                ) AS i(name, institution_type, district)
                WHERE f.name = 'Городское образование'
                ON CONFLICT (name) DO NOTHING;
                INSERT INTO game_education_courses
                    (faction_id, code, title, course_type, reward_coins, reward_xp)
                SELECT f.id, c.code, c.title, c.course_type, c.reward_coins, c.reward_xp
                FROM game_factions f
                CROSS JOIN (VALUES
                    ('history', 'Вводное занятие по истории игрового города', 'lesson', 35, 15),
                    ('civics', 'Занятие по устройству городских служб', 'lesson', 40, 18),
                    ('it_basics', 'Практикум по цифровой грамотности', 'lesson', 45, 20),
                    ('final_quiz', 'Итоговый учебный экзамен по материалам занятий', 'exam', 80, 35)
                ) AS c(code, title, course_type, reward_coins, reward_xp)
                WHERE f.name = 'Городское образование'
                ON CONFLICT (faction_id, code) DO NOTHING;
                CREATE TABLE IF NOT EXISTS game_service_profiles (
                    user_id BIGINT PRIMARY KEY REFERENCES game_players(user_id) ON DELETE CASCADE,
                    faction_id BIGINT NOT NULL REFERENCES game_factions(id) ON DELETE CASCADE,
                    service_rank TEXT NOT NULL DEFAULT 'Стажёр',
                    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (user_id, faction_id)
                );
                CREATE INDEX IF NOT EXISTS game_service_faction_idx
                    ON game_service_profiles (faction_id, service_rank);
                CREATE TABLE IF NOT EXISTS game_service_missions (
                    id BIGSERIAL PRIMARY KEY,
                    faction_id BIGINT NOT NULL REFERENCES game_factions(id) ON DELETE CASCADE,
                    code TEXT NOT NULL,
                    title TEXT NOT NULL,
                    reward_coins INTEGER NOT NULL CHECK (reward_coins > 0),
                    reward_xp INTEGER NOT NULL CHECK (reward_xp >= 0),
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    UNIQUE (faction_id, code)
                );
                CREATE TABLE IF NOT EXISTS game_service_completions (
                    user_id BIGINT NOT NULL REFERENCES game_players(user_id) ON DELETE CASCADE,
                    mission_id BIGINT NOT NULL REFERENCES game_service_missions(id) ON DELETE CASCADE,
                    completed_on DATE NOT NULL DEFAULT CURRENT_DATE,
                    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (user_id, mission_id, completed_on)
                );
                INSERT INTO game_service_missions (faction_id, code, title, reward_coins, reward_xp)
                SELECT f.id, m.code, m.title, m.reward_coins, m.reward_xp
                FROM game_factions f
                CROSS JOIN (VALUES
                    ('briefing', 'Посетить игровое построение и ознакомиться с расписанием', 45, 15),
                    ('report', 'Подготовить учебный отчёт для игрового руководителя', 60, 20),
                    ('community', 'Помочь NPC на городском общественном мероприятии', 75, 25),
                    ('training', 'Посетить учебное занятие и отметить участие', 55, 20)
                ) AS m(code, title, reward_coins, reward_xp)
                WHERE f.name IN ('МВД', 'ФСБ')
                ON CONFLICT (faction_id, code) DO NOTHING;
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
                CREATE TABLE IF NOT EXISTS game_transport_routes (
                    id BIGSERIAL PRIMARY KEY,
                    route_code TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    vehicle_type TEXT NOT NULL DEFAULT 'Автобус',
                    fare INTEGER NOT NULL CHECK (fare > 0),
                    interval_minutes INTEGER NOT NULL CHECK (interval_minutes > 0),
                    active BOOLEAN NOT NULL DEFAULT TRUE
                );
                CREATE TABLE IF NOT EXISTS game_transport_stops (
                    id BIGSERIAL PRIMARY KEY,
                    stop_code TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    district TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS game_transport_route_stops (
                    route_id BIGINT NOT NULL REFERENCES game_transport_routes(id) ON DELETE CASCADE,
                    stop_id BIGINT NOT NULL REFERENCES game_transport_stops(id) ON DELETE CASCADE,
                    stop_order INTEGER NOT NULL CHECK (stop_order > 0),
                    PRIMARY KEY (route_id, stop_id),
                    UNIQUE (route_id, stop_order)
                );
                CREATE TABLE IF NOT EXISTS game_transport_tickets (
                    user_id BIGINT PRIMARY KEY REFERENCES game_players(user_id) ON DELETE CASCADE,
                    quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS game_transport_rides (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES game_players(user_id) ON DELETE CASCADE,
                    route_id BIGINT NOT NULL REFERENCES game_transport_routes(id),
                    from_stop_id BIGINT NOT NULL REFERENCES game_transport_stops(id),
                    to_stop_id BIGINT NOT NULL REFERENCES game_transport_stops(id),
                    fare_paid INTEGER NOT NULL CHECK (fare_paid > 0),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CHECK (from_stop_id <> to_stop_id)
                );
                CREATE INDEX IF NOT EXISTS game_transport_rides_user_idx
                    ON game_transport_rides (user_id, created_at DESC);
                INSERT INTO game_transport_routes
                    (route_code, name, vehicle_type, fare, interval_minutes)
                VALUES
                    ('A1', 'Центральный маршрут', 'Автобус', 20, 15),
                    ('A2', 'Северный маршрут', 'Автобус', 20, 20),
                    ('T1', 'Городской трамвай', 'Трамвай', 20, 12)
                ON CONFLICT (route_code) DO NOTHING;
                INSERT INTO game_transport_stops (stop_code, name, district)
                VALUES
                    ('central', 'Центральная площадь', 'Центр'),
                    ('station', 'Железнодорожный вокзал', 'Центр'),
                    ('hospital', 'Городская больница', 'Северный район'),
                    ('university', 'Городской университет', 'Центр'),
                    ('park', 'Городской парк', 'Северный район'),
                    ('airport', 'Аэропорт', 'Западный район')
                ON CONFLICT (stop_code) DO NOTHING;
                INSERT INTO game_transport_route_stops (route_id, stop_id, stop_order)
                SELECT r.id, s.id, x.stop_order
                FROM (VALUES
                    ('A1', 'central', 1), ('A1', 'station', 2), ('A1', 'university', 3), ('A1', 'hospital', 4),
                    ('A2', 'airport', 1), ('A2', 'park', 2), ('A2', 'hospital', 3), ('A2', 'central', 4),
                    ('T1', 'station', 1), ('T1', 'central', 2), ('T1', 'park', 3), ('T1', 'university', 4)
                ) AS x(route_code, stop_code, stop_order)
                JOIN game_transport_routes r ON r.route_code = x.route_code
                JOIN game_transport_stops s ON s.stop_code = x.stop_code
                ON CONFLICT (route_id, stop_id) DO NOTHING;
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


    async def appoint_government_head(self, actor_id: int, target_id: int, department_id: int) -> tuple[bool, str]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                leader = await connection.fetchval(
                    """SELECT f.id FROM game_factions f
                       JOIN game_faction_members m ON m.faction_id = f.id
                       WHERE f.name = 'Правительство Москвы' AND f.leader_id = $1
                         AND m.user_id = $1 FOR UPDATE OF f""", actor_id
                )
                if leader is None:
                    return False, "Назначать начальников может только лидер Правительства Москвы."
                target = await connection.fetchrow(
                    """SELECT e.user_id FROM game_government_employees e
                       WHERE e.user_id = $1 AND e.department_id = $2 FOR UPDATE""",
                    target_id, department_id
                )
                if target is None:
                    return False, "Игрок должен работать в указанном отделе."
                await connection.execute(
                    """UPDATE game_government_employees SET position = 'Сотрудник'
                       WHERE department_id = $1 AND position = 'Начальник отдела'""", department_id
                )
                await connection.execute(
                    """UPDATE game_government_employees SET position = 'Начальник отдела'
                       WHERE user_id = $1 AND department_id = $2""", target_id, department_id
                )
                return True, "Начальник отдела назначен."


    async def apply_game_service(self, user_id: int, faction_name: str) -> tuple[bool, str]:
        allowed = {"МВД", "ФСБ"}
        if faction_name not in allowed:
            return False, "Выбери одну из игровых служб: МВД или ФСБ."
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                faction = await connection.fetchrow(
                    "SELECT id FROM game_factions WHERE name = $1", faction_name
                )
                if faction is None:
                    return False, "Игровая служба пока не создана."
                member = await connection.fetchval(
                    "SELECT 1 FROM game_faction_members WHERE faction_id = $1 AND user_id = $2",
                    faction["id"], user_id
                )
                if not member:
                    return False, f"Сначала вступи во фракцию «{faction_name}» через /factions."
                current = await connection.fetchval(
                    "SELECT faction_id FROM game_service_profiles WHERE user_id = $1", user_id
                )
                if current is not None:
                    return False, "У тебя уже есть служебная карточка. Сначала выйди из текущей службы."
                await connection.execute(
                    """INSERT INTO game_service_profiles (user_id, faction_id)
                       VALUES ($1, $2)""", user_id, faction["id"]
                )
                return True, f"Ты принят на службу в {faction_name}. Начальное звание: Стажёр."

    async def leave_game_service(self, user_id: int) -> bool:
        result = await self._require_pool().execute(
            "DELETE FROM game_service_profiles WHERE user_id = $1", user_id
        )
        return result.endswith("1")

    async def get_game_service_profile(self, user_id: int) -> asyncpg.Record | None:
        return await self._require_pool().fetchrow(
            """SELECT p.user_id, p.service_rank, p.joined_at, f.name AS faction_name,
                      f.leader_id, gp.username
               FROM game_service_profiles p
               JOIN game_factions f ON f.id = p.faction_id
               JOIN game_players gp ON gp.user_id = p.user_id
               WHERE p.user_id = $1""", user_id
        )

    async def change_game_service_rank(self, actor_id: int, target_id: int, direction: int) -> tuple[bool, str]:
        ranks = ["Стажёр", "Сотрудник", "Старший сотрудник", "Заместитель руководителя", "Руководитель"]
        if direction not in (-1, 1) or actor_id == target_id:
            return False, "Некорректная цель изменения звания."
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                actor = await connection.fetchrow(
                    """SELECT f.id AS faction_id, f.leader_id
                       FROM game_service_profiles p
                       JOIN game_factions f ON f.id = p.faction_id
                       WHERE p.user_id = $1 FOR UPDATE OF f""", actor_id
                )
                if actor is None or actor["leader_id"] != actor_id:
                    return False, "Изменять служебные звания может только лидер фракции."
                target = await connection.fetchrow(
                    """SELECT service_rank FROM game_service_profiles
                       WHERE user_id = $1 AND faction_id = $2 FOR UPDATE""",
                    target_id, actor["faction_id"]
                )
                if target is None:
                    return False, "Игрок не состоит на службе в твоей фракции."
                try:
                    index = ranks.index(target["service_rank"])
                except ValueError:
                    index = 0
                next_index = index + direction
                if next_index < 0 or next_index >= len(ranks) - 1:
                    return False, "Достигнут предел звания. Лидерство определяется отдельно."
                await connection.execute(
                    "UPDATE game_service_profiles SET service_rank = $1 WHERE user_id = $2",
                    ranks[next_index], target_id
                )
                return True, f"Новое служебное звание: {ranks[next_index]}."

    async def list_game_service_missions(self, user_id: int) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            """SELECT m.code, m.title, m.reward_coins, m.reward_xp,
                      EXISTS (
                        SELECT 1 FROM game_service_completions c
                        WHERE c.user_id = $1 AND c.mission_id = m.id
                          AND c.completed_on = CURRENT_DATE
                      ) AS completed_today
               FROM game_service_profiles p
               JOIN game_service_missions m ON m.faction_id = p.faction_id
               WHERE p.user_id = $1 AND m.active = TRUE
               ORDER BY m.id""", user_id
        )

    async def complete_game_service_mission(self, user_id: int, code: str) -> tuple[bool, str]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                mission = await connection.fetchrow(
                    """SELECT m.id, m.reward_coins, m.reward_xp
                       FROM game_service_profiles p
                       JOIN game_service_missions m ON m.faction_id = p.faction_id
                       WHERE p.user_id = $1 AND m.code = $2 AND m.active = TRUE
                       FOR UPDATE OF p""", user_id, code
                )
                if mission is None:
                    return False, "Поручение не найдено для твоей службы. Используй /service tasks."
                inserted = await connection.fetchval(
                    """INSERT INTO game_service_completions (user_id, mission_id, completed_on)
                       VALUES ($1, $2, CURRENT_DATE)
                       ON CONFLICT DO NOTHING RETURNING user_id""",
                    user_id, mission["id"]
                )
                if inserted is None:
                    return False, "Это поручение уже засчитано сегодня."
                await connection.execute(
                    """UPDATE game_players SET coins = coins + $1, xp = xp + $2,
                       updated_at = NOW() WHERE user_id = $3""",
                    mission["reward_coins"], mission["reward_xp"], user_id
                )
                return True, f"Задание засчитано: +{mission['reward_coins']} монет и +{mission['reward_xp']} XP."

    async def get_game_service_roster(self, user_id: int) -> tuple[asyncpg.Record | None, list[asyncpg.Record]]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            faction = await connection.fetchrow(
                """SELECT f.id, f.name, f.leader_id FROM game_service_profiles p
                   JOIN game_factions f ON f.id = p.faction_id
                   WHERE p.user_id = $1""", user_id
            )
            if faction is None:
                return None, []
            members = await connection.fetch(
                """SELECT p.user_id, p.service_rank, gp.username
                   FROM game_service_profiles p
                   JOIN game_players gp ON gp.user_id = p.user_id
                   WHERE p.faction_id = $1
                   ORDER BY CASE p.service_rank
                     WHEN 'Руководитель' THEN 0 WHEN 'Заместитель руководителя' THEN 1
                     WHEN 'Старший сотрудник' THEN 2 WHEN 'Сотрудник' THEN 3 ELSE 4 END,
                     p.joined_at LIMIT 100""", faction["id"]
            )
            return faction, members


    async def list_medical_centers(self) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            """SELECT c.id, c.name, c.district, COUNT(e.user_id)::int AS employees
               FROM game_medical_centers c
               LEFT JOIN game_medical_employees e ON e.center_id = c.id
               GROUP BY c.id ORDER BY c.id"""
        )

    async def apply_medical_center(self, user_id: int, username: str, center_id: int) -> tuple[bool, str]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """INSERT INTO game_players (user_id, username) VALUES ($1, $2)
                       ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username""",
                    user_id, username[:64]
                )
                center = await connection.fetchrow(
                    """SELECT c.id, c.name, c.faction_id FROM game_medical_centers c
                       WHERE c.id = $1""", center_id
                )
                if center is None:
                    return False, "Медицинский центр не найден. Используй /med centers."
                member = await connection.fetchval(
                    """SELECT 1 FROM game_faction_members
                       WHERE faction_id = $1 AND user_id = $2""",
                    center["faction_id"], user_id
                )
                if not member:
                    return False, "Сначала вступи во фракцию «Городская больница» через /factions."
                current = await connection.fetchval(
                    "SELECT 1 FROM game_medical_employees WHERE user_id = $1", user_id
                )
                if current:
                    return False, "Ты уже работаешь в медицинской организации."
                await connection.execute(
                    """INSERT INTO game_medical_employees (user_id, faction_id, center_id)
                       VALUES ($1, $2, $3)""", user_id, center["faction_id"], center_id
                )
                return True, f"Ты принят в организацию «{center['name']}» на должность «Стажёр»."

    async def leave_medical_center(self, user_id: int) -> bool:
        result = await self._require_pool().execute(
            "DELETE FROM game_medical_employees WHERE user_id = $1", user_id
        )
        return result.endswith("1")

    async def get_medical_profile(self, user_id: int) -> asyncpg.Record | None:
        return await self._require_pool().fetchrow(
            """SELECT e.user_id, e.job_title, e.joined_at, c.name AS center_name,
                      c.district, f.leader_id, p.username
               FROM game_medical_employees e
               JOIN game_medical_centers c ON c.id = e.center_id
               JOIN game_factions f ON f.id = e.faction_id
               JOIN game_players p ON p.user_id = e.user_id
               WHERE e.user_id = $1""", user_id
        )

    async def change_medical_job_title(self, actor_id: int, target_id: int, direction: int) -> tuple[bool, str]:
        titles = ["Стажёр", "Медицинский сотрудник", "Старший сотрудник", "Заместитель главврача", "Главврач"]
        if direction not in (-1, 1) or actor_id == target_id:
            return False, "Некорректная цель изменения должности."
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                actor = await connection.fetchrow(
                    """SELECT e.faction_id, f.leader_id FROM game_medical_employees e
                       JOIN game_factions f ON f.id = e.faction_id
                       WHERE e.user_id = $1 FOR UPDATE OF f""", actor_id
                )
                if actor is None or actor["leader_id"] != actor_id:
                    return False, "Назначать должности может только лидер фракции больницы."
                target = await connection.fetchrow(
                    """SELECT job_title FROM game_medical_employees
                       WHERE user_id = $1 AND faction_id = $2 FOR UPDATE""",
                    target_id, actor["faction_id"]
                )
                if target is None:
                    return False, "Игрок не работает в этой медицинской организации."
                try:
                    index = titles.index(target["job_title"])
                except ValueError:
                    index = 0
                next_index = index + direction
                if next_index < 0 or next_index >= len(titles) - 1:
                    return False, "Достигнут предел должности. Руководство определяется лидерством фракции."
                await connection.execute(
                    "UPDATE game_medical_employees SET job_title = $1 WHERE user_id = $2",
                    titles[next_index], target_id
                )
                return True, f"Новая должность: {titles[next_index]}."

    async def list_medical_missions(self, user_id: int) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            """SELECT m.code, m.title, m.reward_coins, m.reward_xp,
                      EXISTS (
                        SELECT 1 FROM game_medical_completions c
                        WHERE c.user_id = $1 AND c.mission_id = m.id
                          AND c.completed_on = CURRENT_DATE
                      ) AS completed_today
               FROM game_medical_employees e
               JOIN game_medical_missions m ON m.faction_id = e.faction_id
               WHERE e.user_id = $1 AND m.active = TRUE ORDER BY m.id""", user_id
        )

    async def complete_medical_mission(self, user_id: int, code: str) -> tuple[bool, str]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                mission = await connection.fetchrow(
                    """SELECT m.id, m.reward_coins, m.reward_xp
                       FROM game_medical_employees e
                       JOIN game_medical_missions m ON m.faction_id = e.faction_id
                       WHERE e.user_id = $1 AND m.code = $2 AND m.active = TRUE
                       FOR UPDATE OF e""", user_id, code
                )
                if mission is None:
                    return False, "Задание не найдено. Используй /med tasks."
                inserted = await connection.fetchval(
                    """INSERT INTO game_medical_completions (user_id, mission_id, completed_on)
                       VALUES ($1, $2, CURRENT_DATE)
                       ON CONFLICT DO NOTHING RETURNING user_id""",
                    user_id, mission["id"]
                )
                if inserted is None:
                    return False, "Это задание уже засчитано сегодня."
                await connection.execute(
                    """UPDATE game_players SET coins = coins + $1, xp = xp + $2,
                       updated_at = NOW() WHERE user_id = $3""",
                    mission["reward_coins"], mission["reward_xp"], user_id
                )
                return True, f"Задание выполнено: +{mission['reward_coins']} монет и +{mission['reward_xp']} XP."

    async def get_medical_roster(self, user_id: int) -> tuple[asyncpg.Record | None, list[asyncpg.Record]]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            center = await connection.fetchrow(
                """SELECT c.id, c.name, f.name AS faction_name, f.leader_id
                   FROM game_medical_employees e
                   JOIN game_medical_centers c ON c.id = e.center_id
                   JOIN game_factions f ON f.id = e.faction_id
                   WHERE e.user_id = $1""", user_id
            )
            if center is None:
                return None, []
            members = await connection.fetch(
                """SELECT e.user_id, e.job_title, p.username, c.name AS center_name
                   FROM game_medical_employees e
                   JOIN game_players p ON p.user_id = e.user_id
                   JOIN game_medical_centers c ON c.id = e.center_id
                   WHERE e.faction_id = (
                       SELECT faction_id FROM game_medical_employees WHERE user_id = $1
                   )
                   ORDER BY CASE e.job_title
                     WHEN 'Главврач' THEN 0 WHEN 'Заместитель главврача' THEN 1
                     WHEN 'Старший сотрудник' THEN 2 WHEN 'Медицинский сотрудник' THEN 3 ELSE 4 END,
                     e.joined_at LIMIT 100""", user_id
            )
            return center, members


    async def list_education_institutions(self) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            """SELECT i.id, i.name, i.institution_type, i.district,
                      COUNT(s.user_id)::int AS students
               FROM game_education_institutions i
               LEFT JOIN game_education_students s ON s.institution_id = i.id
               GROUP BY i.id ORDER BY i.id"""
        )

    async def enroll_education_student(self, user_id: int, username: str, institution_id: int) -> tuple[bool, str]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """INSERT INTO game_players (user_id, username) VALUES ($1, $2)
                       ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username""",
                    user_id, username[:64]
                )
                institution = await connection.fetchrow(
                    """SELECT i.id, i.name, i.faction_id FROM game_education_institutions i
                       WHERE i.id = $1""", institution_id
                )
                if institution is None:
                    return False, "Учебное заведение не найдено. Используй /edu institutions."
                member = await connection.fetchval(
                    """SELECT 1 FROM game_faction_members
                       WHERE faction_id = $1 AND user_id = $2""",
                    institution["faction_id"], user_id
                )
                if not member:
                    return False, "Сначала вступи во фракцию «Городское образование» через /factions."
                current = await connection.fetchval(
                    "SELECT 1 FROM game_education_students WHERE user_id = $1", user_id
                )
                if current:
                    return False, "Ты уже зачислен в учебное заведение. Сначала используй /edu leave."
                group_id = await connection.fetchval(
                    """SELECT id FROM game_education_groups
                       WHERE institution_id = $1 ORDER BY id LIMIT 1""", institution_id
                )
                await connection.execute(
                    """INSERT INTO game_education_students (user_id, faction_id, institution_id, group_id)
                       VALUES ($1, $2, $3, $4)""",
                    user_id, institution["faction_id"], institution_id, group_id
                )
                return True, f"Ты зачислен: «{institution['name']}»."

    async def leave_education_institution(self, user_id: int) -> bool:
        result = await self._require_pool().execute(
            "DELETE FROM game_education_students WHERE user_id = $1", user_id
        )
        return result.endswith("1")

    async def get_education_profile(self, user_id: int) -> asyncpg.Record | None:
        return await self._require_pool().fetchrow(
            """SELECT s.user_id, s.enrolled_at, i.name AS institution_name,
                      i.institution_type, i.district, p.username, g.group_name, g.group_code
               FROM game_education_students s
               JOIN game_education_institutions i ON i.id = s.institution_id
               LEFT JOIN game_education_groups g ON g.id = s.group_id
               JOIN game_players p ON p.user_id = s.user_id
               WHERE s.user_id = $1""", user_id
        )

    async def list_education_groups(self, institution_id: int | None = None) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            """SELECT g.id, g.group_code, g.group_name, i.name AS institution_name,
                      COUNT(s.user_id)::int AS students
               FROM game_education_groups g
               JOIN game_education_institutions i ON i.id = g.institution_id
               LEFT JOIN game_education_students s ON s.group_id = g.id
               WHERE ($1::BIGINT IS NULL OR g.institution_id = $1)
               GROUP BY g.id, i.name ORDER BY i.id, g.id""", institution_id
        )

    async def list_education_courses(self, user_id: int) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            """SELECT c.code, c.title, c.course_type, c.reward_coins, c.reward_xp,
                      EXISTS (
                        SELECT 1 FROM game_education_completions x
                        WHERE x.user_id = $1 AND x.course_id = c.id
                          AND x.completed_on = CURRENT_DATE
                      ) AS completed_today
               FROM game_education_students s
               JOIN game_education_courses c ON c.faction_id = s.faction_id
               WHERE s.user_id = $1 AND c.active = TRUE ORDER BY c.id""", user_id
        )

    async def complete_education_course(self, user_id: int, code: str, course_type: str) -> tuple[bool, str]:
        if course_type not in ("lesson", "exam"):
            return False, "Неизвестный тип учебной активности."
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                course = await connection.fetchrow(
                    """SELECT c.id, c.title, c.course_type, c.reward_coins, c.reward_xp
                       FROM game_education_students s
                       JOIN game_education_courses c ON c.faction_id = s.faction_id
                       WHERE s.user_id = $1 AND c.code = $2 AND c.course_type = $3
                         AND c.active = TRUE
                       FOR UPDATE OF s""", user_id, code, course_type
                )
                if course is None:
                    return False, "Учебная активность не найдена. Используй /edu classes."
                if course_type == "exam":
                    lessons = await connection.fetchval(
                        """SELECT COUNT(*) FROM game_education_courses c
                           WHERE c.faction_id = (
                             SELECT faction_id FROM game_education_students WHERE user_id = $1
                           ) AND c.course_type = 'lesson' AND c.active = TRUE
                             AND EXISTS (
                               SELECT 1 FROM game_education_completions x
                               WHERE x.user_id = $1 AND x.course_id = c.id
                             )""", user_id
                    )
                    required = await connection.fetchval(
                        """SELECT COUNT(*) FROM game_education_courses
                           WHERE faction_id = (
                             SELECT faction_id FROM game_education_students WHERE user_id = $1
                           ) AND course_type = 'lesson' AND active = TRUE""", user_id
                    )
                    if lessons < required:
                        return False, "Сначала заверши все доступные занятия, затем сдавай экзамен."
                inserted = await connection.fetchval(
                    """INSERT INTO game_education_completions (user_id, course_id, completed_on)
                       VALUES ($1, $2, CURRENT_DATE)
                       ON CONFLICT DO NOTHING RETURNING user_id""",
                    user_id, course["id"]
                )
                if inserted is None:
                    return False, "Эта активность уже засчитана сегодня."
                await connection.execute(
                    """UPDATE game_players SET coins = coins + $1, xp = xp + $2,
                       updated_at = NOW() WHERE user_id = $3""",
                    course["reward_coins"], course["reward_xp"], user_id
                )
                return True, f"«{course['title']}»: +{course['reward_coins']} монет, +{course['reward_xp']} XP."

    async def get_education_roster(self, user_id: int) -> tuple[asyncpg.Record | None, list[asyncpg.Record]]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            institution = await connection.fetchrow(
                """SELECT i.id, i.name, f.name AS faction_name
                   FROM game_education_students s
                   JOIN game_education_institutions i ON i.id = s.institution_id
                   JOIN game_factions f ON f.id = s.faction_id
                   WHERE s.user_id = $1""", user_id
            )
            if institution is None:
                return None, []
            students = await connection.fetch(
                """SELECT s.user_id, p.username, i.name AS institution_name,
                          g.group_code, g.group_name, s.enrolled_at
                   FROM game_education_students s
                   JOIN game_players p ON p.user_id = s.user_id
                   JOIN game_education_institutions i ON i.id = s.institution_id
                   LEFT JOIN game_education_groups g ON g.id = s.group_id
                   WHERE s.institution_id = $1
                   ORDER BY s.enrolled_at LIMIT 100""", institution["id"]
            )
            return institution, students


    async def list_transport_routes(self) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            """SELECT r.id, r.route_code, r.name, r.vehicle_type, r.fare,
                      r.interval_minutes, COUNT(rs.stop_id)::int AS stops
               FROM game_transport_routes r
               LEFT JOIN game_transport_route_stops rs ON rs.route_id = r.id
               WHERE r.active = TRUE
               GROUP BY r.id ORDER BY r.id"""
        )

    async def list_transport_stops(self, route_id: int) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            """SELECT s.id, s.name, s.district, rs.stop_order
               FROM game_transport_route_stops rs
               JOIN game_transport_stops s ON s.id = rs.stop_id
               JOIN game_transport_routes r ON r.id = rs.route_id
               WHERE rs.route_id = $1 AND r.active = TRUE
               ORDER BY rs.stop_order""", route_id
        )

    async def get_transport_ticket_count(self, user_id: int) -> int:
        return int(await self._require_pool().fetchval(
            "SELECT quantity FROM game_transport_tickets WHERE user_id = $1", user_id
        ) or 0)

    async def buy_transport_tickets(self, user_id: int, username: str, quantity: int) -> tuple[bool, str]:
        if not 1 <= quantity <= 10:
            return False, "За одну покупку можно приобрести от 1 до 10 билетов."
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """INSERT INTO game_players (user_id, username) VALUES ($1, $2)
                       ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username""",
                    user_id, username[:64]
                )
                player = await connection.fetchrow(
                    "SELECT coins FROM game_players WHERE user_id = $1 FOR UPDATE", user_id
                )
                price = quantity * 20
                if int(player["coins"]) < price:
                    return False, f"Недостаточно монет. Нужно {price}."
                await connection.execute(
                    "UPDATE game_players SET coins = coins - $2, updated_at = NOW() WHERE user_id = $1",
                    user_id, price
                )
                await connection.execute(
                    """INSERT INTO game_transport_tickets (user_id, quantity)
                       VALUES ($1, $2)
                       ON CONFLICT (user_id) DO UPDATE
                       SET quantity = game_transport_tickets.quantity + EXCLUDED.quantity,
                           updated_at = NOW()""", user_id, quantity
                )
                return True, f"Куплено билетов: {quantity}. Списано {price} монет."

    async def ride_city_transport(self, user_id: int, route_id: int, from_stop_id: int, to_stop_id: int) -> tuple[bool, str]:
        if from_stop_id == to_stop_id:
            return False, "Остановки отправления и назначения должны различаться."
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                route = await connection.fetchrow(
                    """SELECT id, name, fare FROM game_transport_routes
                       WHERE id = $1 AND active = TRUE FOR UPDATE""", route_id
                )
                if route is None:
                    return False, "Маршрут не найден. Используй /bus routes."
                stops = await connection.fetchval(
                    """SELECT COUNT(*) FROM game_transport_route_stops
                       WHERE route_id = $1 AND stop_id = ANY($2::BIGINT[])""",
                    route_id, [from_stop_id, to_stop_id]
                )
                if stops != 2:
                    return False, "Обе остановки должны входить в выбранный маршрут."
                ordered = await connection.fetchval(
                    """SELECT BOOL_AND(a.stop_order < b.stop_order)
                       FROM game_transport_route_stops a
                       JOIN game_transport_route_stops b ON b.route_id = a.route_id
                       WHERE a.route_id = $1 AND a.stop_id = $2 AND b.stop_id = $3""",
                    route_id, from_stop_id, to_stop_id
                )
                if not ordered:
                    return False, "Выбери остановки в порядке движения маршрута."
                ticket = await connection.fetchrow(
                    "SELECT quantity FROM game_transport_tickets WHERE user_id = $1 FOR UPDATE",
                    user_id
                )
                if ticket is None or ticket["quantity"] < 1:
                    return False, "Нет билетов. Купи их командой /bus ticket 1."
                await connection.execute(
                    """UPDATE game_transport_tickets
                       SET quantity = quantity - 1, updated_at = NOW()
                       WHERE user_id = $1""", user_id
                )
                await connection.execute(
                    """INSERT INTO game_transport_rides
                       (user_id, route_id, from_stop_id, to_stop_id, fare_paid)
                       VALUES ($1, $2, $3, $4, $5)""",
                    user_id, route_id, from_stop_id, to_stop_id, route["fare"]
                )
                await connection.execute(
                    "UPDATE game_players SET xp = xp + 5, updated_at = NOW() WHERE user_id = $1",
                    user_id
                )
                names = await connection.fetchrow(
                    """SELECT a.name AS from_name, b.name AS to_name
                       FROM game_transport_stops a, game_transport_stops b
                       WHERE a.id = $1 AND b.id = $2""", from_stop_id, to_stop_id
                )
                return True, f"Поездка «{route['name']}»: {names['from_name']} → {names['to_name']}. +5 XP."

    async def get_transport_ride_history(self, user_id: int) -> list[asyncpg.Record]:
        return await self._require_pool().fetch(
            """SELECT r.name AS route_name, a.name AS from_name, b.name AS to_name,
                      t.created_at
               FROM game_transport_rides t
               JOIN game_transport_routes r ON r.id = t.route_id
               JOIN game_transport_stops a ON a.id = t.from_stop_id
               JOIN game_transport_stops b ON b.id = t.to_stop_id
               WHERE t.user_id = $1 ORDER BY t.created_at DESC LIMIT 10""", user_id
        )



database = Database()
