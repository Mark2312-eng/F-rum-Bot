"""Canonical project staff-role catalogue and scoped permissions."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StaffRole:
    key: str
    title: str
    department: str
    rank: int
    permissions: frozenset[str]


STAFF_ROLES = (
    StaffRole("project_team", "Команда проекта", "leadership", 95, frozenset(["staff_view","staff_manage","testing_manage"])),
    StaffRole("special_admin", "Специальный администратор", "administration", 90, frozenset(["staff_view","moderation","reports","settings","testing_manage"])),
    StaffRole("deputy_special_admin", "Зам. спец. администратора", "administration", 88, frozenset(["staff_view","moderation","reports","settings","testing_manage"])),
    StaffRole("head_administrator", "Главный администратор", "administration", 85, frozenset(["staff_view","moderation","reports","settings","testing_manage"])),
    StaffRole("deputy_chief_admin", "Зам. главного администратора", "administration", 83, frozenset(["staff_view","moderation","reports","settings","testing_manage"])),
    StaffRole("admin_curator", "Куратор администрации", "administration", 80, frozenset(["staff_view","moderation","reports","settings","testing_manage"])),
    StaffRole("senior_admin", "Старший администратор", "administration", 75, frozenset(["moderation","reports","settings"])),
    StaffRole("administrator", "Администратор", "administration", 70, frozenset(["moderation","reports"])),
    StaffRole("senior_moderator", "Старший модератор", "moderation", 60, frozenset(["moderation","reports"])),
    StaffRole("chat_moderator", "Модератор", "moderation", 55, frozenset(["moderation","reports"])),
    StaffRole("junior_moderator", "Младший модератор", "moderation", 50, frozenset(["moderation","reports"])),
    StaffRole("leader", "Лидер", "community", 45, frozenset(["staff_view"])),
    StaffRole("registered_user", "Зарегистрированный пользователь", "community", 1, frozenset([])),
    StaffRole("chief_tech_specialist", "Главный технический специалист", "technical", 80, frozenset(["technical","staff_view"])),
    StaffRole("deputy_gts", "Заместитель ГТС", "technical", 75, frozenset(["technical"])),
    StaffRole("tech_curator", "Куратор технических специалистов", "technical", 70, frozenset(["technical","staff_view"])),
    StaffRole("deputy_tech_curator", "Зам. куратора тех. специалистов", "technical", 65, frozenset(["technical"])),
    StaffRole("tech_specialist", "Технический специалист", "technical", 60, frozenset(["technical"])),
    StaffRole("deputy_chief_tester", "Заместитель главного тестировщика", "quality", 75, frozenset(["testing_review","testing_manage","staff_view"])),
    StaffRole("qa_head", "Глава контроля качества", "quality", 70, frozenset(["testing_review","testing_manage","staff_view"])),
    StaffRole("qa_specialist", "Контроль качества", "quality", 60, frozenset(["testing_review"])),
    StaffRole("senior_tester", "Старший тестировщик", "quality", 55, frozenset(["testing_review"])),
    StaffRole("tester", "Тестировщик", "quality", 50, frozenset(["testing_review"])),
    StaffRole("junior_tester", "Младший тестировщик", "quality", 45, frozenset(["testing_review"])),
    StaffRole("discord_moderation_lead", "Руководитель модераторов (Discord)", "discord", 70, frozenset(["discord_moderation","staff_view"])),
    StaffRole("deputy_discord_moderation_lead", "Зам. руководителя модераторов", "discord", 65, frozenset(["discord_moderation"])),
    StaffRole("gm_curator", "Куратор ГМ", "administration", 65, frozenset(["moderation","reports"])),
    StaffRole("principal_deputy_chief_admin", "Осн. зам. главного администратора", "administration", 84, frozenset(["staff_view","moderation","reports","settings","testing_manage"])),
    StaffRole("organizations_curator", "Куратор организаций", "organizations", 70, frozenset(["organizations","staff_view"])),
    StaffRole("support_agents_curator", "Куратор агентов поддержки", "support", 70, frozenset(["support","staff_view"])),
    StaffRole("senior_social_orgs_supervisor", "Ст. следящий за соц. организациями", "organizations", 60, frozenset(["organizations"])),
    StaffRole("senior_support_agents_supervisor", "Ст. следящий за агентами поддержки", "support", 60, frozenset(["support"])),
    StaffRole("deputy_organizations_curator", "Зам. куратора организаций", "organizations", 65, frozenset(["organizations"])),
    StaffRole("deputy_support_agents_curator", "Зам. куратора агентов поддержки", "support", 65, frozenset(["support"])),
    StaffRole("senior_criminal_orgs_supervisor", "Ст. следящий за крим. организациями", "organizations", 60, frozenset(["organizations"])),
    StaffRole("supervisor_umvd", "Следящий за УМВД", "organizations", 50, frozenset(["organizations"])),
    StaffRole("supervisor_army", "Следящий за армией", "organizations", 50, frozenset(["organizations"])),
    StaffRole("supervisor_support_agents", "Следящий за агентами поддержки", "support", 50, frozenset(["support"])),
    StaffRole("supervisor_gibdd", "Следящий за ГИБДД", "organizations", 50, frozenset(["organizations"])),
    StaffRole("supervisor_fsb", "Следящий за ФСБ", "organizations", 50, frozenset(["organizations"])),
    StaffRole("supervisor_government", "Следящий за правительством", "organizations", 50, frozenset(["organizations"])),
    StaffRole("supervisor_l_opg", "Следящий за Л-ОПГ", "organizations", 50, frozenset(["organizations"])),
    StaffRole("supervisor_v_opg", "Следящий за В-ОПГ", "organizations", 50, frozenset(["organizations"])),
    StaffRole("supervisor_a_opg", "Следящий за А-ОПГ", "organizations", 50, frozenset(["organizations"])),
    StaffRole("red_roles_collector", "Собиратель красных ролей", "organizations", 40, frozenset(["organizations"])),
)

ROLE_CATALOG = {role.key: role for role in STAFF_ROLES}
DEPARTMENT_TITLES = {
    "leadership": "Руководство проекта",
    "administration": "Администрация",
    "moderation": "Модерация",
    "community": "Сообщество",
    "technical": "Технический отдел",
    "quality": "Контроль качества и тестирование",
    "discord": "Discord",
    "organizations": "Организации",
    "support": "Агенты поддержки",
}
