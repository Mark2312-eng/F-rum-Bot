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
    StaffRole("project_team", "Совет проекта", "leadership", 95, frozenset(["staff_view","staff_manage","testing_manage"])),
    StaffRole("special_admin", "Верховный администратор", "administration", 90, frozenset(["staff_view","moderation","reports","settings","testing_manage"])),
    StaffRole("deputy_special_admin", "Первый заместитель верховного администратора", "administration", 88, frozenset(["staff_view","moderation","reports","settings","testing_manage"])),
    StaffRole("head_administrator", "Генеральный администратор", "administration", 85, frozenset(["staff_view","moderation","reports","settings","testing_manage"])),
    StaffRole("deputy_chief_admin", "Заместитель генерального администратора", "administration", 83, frozenset(["staff_view","moderation","reports","settings","testing_manage"])),
    StaffRole("admin_curator", "Руководитель администрации", "administration", 80, frozenset(["staff_view","moderation","reports","settings","testing_manage"])),
    StaffRole("senior_admin", "Старший администратор", "administration", 75, frozenset(["moderation","reports","settings"])),
    StaffRole("administrator", "Администратор направления", "administration", 70, frozenset(["moderation","reports"])),
    StaffRole("senior_moderator", "Руководитель модерации", "moderation", 60, frozenset(["moderation","reports"])),
    StaffRole("chat_moderator", "Инспектор сообщества", "moderation", 55, frozenset(["moderation","reports"])),
    StaffRole("junior_moderator", "Младший инспектор сообщества", "moderation", 50, frozenset(["moderation","reports"])),
    StaffRole("leader", "Амбассадор сообщества", "community", 45, frozenset(["staff_view"])),
    StaffRole("registered_user", "Участник сообщества", "community", 1, frozenset([])),
    StaffRole("chief_tech_specialist", "Технический директор", "technical", 80, frozenset(["technical","staff_view"])),
    StaffRole("deputy_gts", "Заместитель технического директора", "technical", 75, frozenset(["technical"])),
    StaffRole("tech_curator", "Руководитель инженерного отдела", "technical", 70, frozenset(["technical","staff_view"])),
    StaffRole("deputy_tech_curator", "Заместитель руководителя инженерного отдела", "technical", 65, frozenset(["technical"])),
    StaffRole("tech_specialist", "Инженер платформы", "technical", 60, frozenset(["technical"])),
    StaffRole("deputy_chief_tester", "Заместитель руководителя QA", "quality", 75, frozenset(["testing_review","testing_manage","staff_view"])),
    StaffRole("qa_head", "Руководитель QA-направления", "quality", 70, frozenset(["testing_review","testing_manage","staff_view"])),
    StaffRole("qa_specialist", "QA-аналитик", "quality", 60, frozenset(["testing_review"])),
    StaffRole("senior_tester", "Старший тест-инженер", "quality", 55, frozenset(["testing_review"])),
    StaffRole("tester", "Тест-инженер", "quality", 50, frozenset(["testing_review"])),
    StaffRole("junior_tester", "Младший тест-инженер", "quality", 45, frozenset(["testing_review"])),
    StaffRole("discord_moderation_lead", "Руководитель Discord-направления", "discord", 70, frozenset(["discord_moderation","staff_view"])),
    StaffRole("deputy_discord_moderation_lead", "Заместитель руководителя Discord-направления", "discord", 65, frozenset(["discord_moderation"])),
    StaffRole("gm_curator", "Куратор игровых сообществ", "administration", 65, frozenset(["moderation","reports"])),
    StaffRole("principal_deputy_chief_admin", "Первый заместитель генерального администратора", "administration", 84, frozenset(["staff_view","moderation","reports","settings","testing_manage"])),
    StaffRole("organizations_curator", "Руководитель подразделений", "organizations", 70, frozenset(["organizations","staff_view"])),
    StaffRole("support_agents_curator", "Руководитель службы заботы", "support", 70, frozenset(["support","staff_view"])),
    StaffRole("senior_social_orgs_supervisor", "Старший координатор общественных направлений", "organizations", 60, frozenset(["organizations"])),
    StaffRole("senior_support_agents_supervisor", "Старший координатор службы заботы", "support", 60, frozenset(["support"])),
    StaffRole("deputy_organizations_curator", "Заместитель руководителя подразделений", "organizations", 65, frozenset(["organizations"])),
    StaffRole("deputy_support_agents_curator", "Заместитель руководителя службы заботы", "support", 65, frozenset(["support"])),
    StaffRole("senior_criminal_orgs_supervisor", "Старший координатор специальных сообществ", "organizations", 60, frozenset(["organizations"])),
    StaffRole("supervisor_umvd", "Координатор подразделения «Патруль»", "organizations", 50, frozenset(["organizations"])),
    StaffRole("supervisor_army", "Координатор подразделения «Рубеж»", "organizations", 50, frozenset(["organizations"])),
    StaffRole("supervisor_support_agents", "Координатор службы заботы", "support", 50, frozenset(["support"])),
    StaffRole("supervisor_gibdd", "Координатор подразделения «Магистраль»", "organizations", 50, frozenset(["organizations"])),
    StaffRole("supervisor_fsb", "Координатор подразделения «Контур»", "organizations", 50, frozenset(["organizations"])),
    StaffRole("supervisor_government", "Координатор государственного направления", "organizations", 50, frozenset(["organizations"])),
    StaffRole("supervisor_l_opg", "Координатор сообщества «Легион»", "organizations", 50, frozenset(["organizations"])),
    StaffRole("supervisor_v_opg", "Координатор сообщества «Вектор»", "organizations", 50, frozenset(["organizations"])),
    StaffRole("supervisor_a_opg", "Координатор сообщества «Альянс»", "organizations", 50, frozenset(["organizations"])),
    StaffRole("red_roles_collector", "Координатор специальных статусов", "organizations", 40, frozenset(["organizations"])),
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
