"""Экраны админки: статистика и группы — как данные, без Telegram.

Перенесено из ``tgbot/handlers/admin.py`` на этапе 1 (план 173).
Функции возвращают ``(текст, Keyboard)``.

Проверено: 13 экранов (сводка, два подразделения, три фильтра групп по
двум страницам, чаты, преподаватели, настройки) дают тот же текст,
раскладку и действия, что до переноса.
"""
from __future__ import annotations

import datetime

from common.schedule import is_vuz, strip_unit
from core import source_state
from core.keyboard import Keyboard, btn, kb
from infrastructure.database.models import User
from infrastructure.database.repo.requests import RequestsRepo

GROUPS_PER_PAGE = 10


async def groups_index(repo: RequestsRepo) -> dict[str, list[User]]:
    """Группа -> её студенты, без преподавателей и без пустых групп."""
    users = await repo.users.get_all()
    index: dict[str, list[User]] = {}
    for u in users:
        if u.role == "teacher" or not u.group:
            continue
        index.setdefault(u.group, []).append(u)
    return index


def group_sort_key(item: tuple[str, list[User]]) -> tuple:
    """По размеру группы, крупные сверху; при равенстве — по алфавиту."""
    name, members = item
    return (-len(members), strip_unit(name))


async def build_stats(repo: RequestsRepo) -> tuple[str, Keyboard]:
    """Сводка по боту с разделением на колледж и вуз.

    Раньше всё считалось в кучу: 129 групп, общее число пар, общая
    аудитория. По такой цифре нельзя понять, где проблема — в вузе или
    в колледже, — а источники у них разные и ломаются независимо.
    """
    users = await repo.users.get_all()
    now = datetime.datetime.now()
    week_ago = now - datetime.timedelta(days=7)

    # Преподаватели не относятся ни к одному подразделению: у них нет
    # группы, а is_vuz(None) == False записал бы их в колледж.
    students = [u for u in users if u.role != "teacher"]
    vuz_users = [u for u in students if is_vuz(u.group)]
    college_users = [u for u in students if not is_vuz(u.group)]
    teachers = [u for u in users if u.role == "teacher"]
    subscribed = sum(1 for u in users if u.subscribed)
    active = sum(1 for u in users if u.last_seen and u.last_seen >= week_ago)

    groups = await repo.college_lessons.get_groups()
    vuz_groups = [g for g in groups if is_vuz(g)]
    college_groups = [g for g in groups if not is_vuz(g)]

    # Считаем по подразделению группы, а не по source: у колледжа
    # source='site', у вуза — 'vuz'. Привязка к source сломалась бы при
    # смене источника.
    base_vuz = await repo.base_lessons.count(vuz=True)
    base_college = await repo.base_lessons.count(vuz=False)
    subs_vuz = await repo.substitutions.count(vuz=True)
    subs_college = await repo.substitutions.count(vuz=False)

    lines = ["📊 <b>Статистика</b>\n"]
    lines.append(f"👥 Пользователей: <b>{len(users)}</b> · "
                 f"активных (7д): <b>{active}</b> · подписаны: <b>{subscribed}</b>")
    lines.append("")
    lines.append("<b>Подразделения</b>")
    lines.append(f"🎓 Колледж — студентов <b>{len(college_users)}</b>, "
                 f"групп <b>{len(college_groups)}</b>")
    lines.append(f"🏛 Вуз — студентов <b>{len(vuz_users)}</b>, "
                 f"групп <b>{len(vuz_groups)}</b>")
    if teachers:
        lines.append(f"👨‍🏫 Преподавателей: <b>{len(teachers)}</b>")
    lines.append("")
    lines.append("<b>Расписание</b>")
    lines.append(f"🎓 Колледж: пар <b>{base_college}</b> · замен <b>{subs_college}</b>")
    lines.append(f"🏛 Вуз: пар <b>{base_vuz}</b> · замен <b>{subs_vuz}</b>")
    lines.append("")

    # Источники независимы: ЭИОС может лежать, а файл вуза быть свежим.
    ok_college = await source_state.last_ok(repo)
    if await source_state.is_stale(repo):
        when = f"с {ok_college:%d.%m %H:%M}" if ok_college else "никогда"
        lines.append(f"⚠️ <b>ЭИОС колледжа не отвечает</b> (успех: {when})")
    elif ok_college:
        lines.append(f"✅ ЭИОС колледжа: {ok_college:%d.%m %H:%M}")

    ok_vuz = await source_state.last_ok_vuz(repo)
    if await source_state.is_stale_vuz(repo):
        when = f"с {ok_vuz:%d.%m %H:%M}" if ok_vuz else "ещё не было"
        lines.append(f"⚠️ <b>Синхронизация вуза не проходила</b> ({when})")
    elif ok_vuz:
        lines.append(f"✅ Вуз: {ok_vuz:%d.%m %H:%M}")

    rows = [
        [btn("🎓 Колледж подробно", "adm:stats:college"),
         btn("🏛 Вуз подробно", "adm:stats:vuz")],
        [btn("👥 Все группы", "adm:stats:groups")],
        [btn("⬅️ Назад", "adm:back")],
    ]
    return "\n".join(lines), kb(*rows)


async def build_stats_unit(repo: RequestsRepo, unit: str) -> tuple[str, Keyboard]:
    """Подробности по одному подразделению."""
    is_v = unit == "vuz"
    users = await repo.users.get_all()
    # Только студенты: у преподавателя группы нет, и он попадал бы
    # в колледж.
    students = [u for u in users if u.role != "teacher"]
    mine = [u for u in students if is_vuz(u.group) == is_v]
    subscribed = sum(1 for u in mine if u.subscribed)

    groups = [g for g in await repo.college_lessons.get_groups()
              if is_vuz(g) == is_v]
    base = await repo.base_lessons.count(vuz=is_v)
    subs = await repo.substitutions.count(vuz=is_v)

    title = "🏛 Вуз" if is_v else "🎓 Колледж"
    lines = [f"{title} — подробно\n"]
    lines.append(f"Студентов: <b>{len(mine)}</b> · подписаны: <b>{subscribed}</b>")
    lines.append(f"Групп в расписании: <b>{len(groups)}</b>")
    lines.append(f"Пар в базе: <b>{base}</b> · замен: <b>{subs}</b>")

    if is_v:
        info = await repo.vuz_groups.all()
        by_form: dict[str, int] = {}
        for g in info:
            by_form[g.form] = by_form.get(g.form, 0) + 1
        if by_form:
            names = {"full": "очная", "part": "очно-заочная"}
            parts = ", ".join(f"{names.get(k, k)} {v}"
                              for k, v in sorted(by_form.items()))
            lines.append(f"Формы обучения: {parts}")

    # Топ групп по числу студентов. Считаем тем же помощником, что и
    # экран «Все группы»: два независимых счётчика однажды разойдутся,
    # и будет непонятно, какой цифре верить.
    per_group = {
        g: len(members)
        for g, members in (await groups_index(repo)).items()
        if is_vuz(g) == is_v
    }
    if per_group:
        lines.append("")
        lines.append("<b>Крупнейшие группы</b>")
        for g, n in sorted(per_group.items(), key=lambda x: -x[1])[:8]:
            lines.append(f"  {strip_unit(g)} — {n}")

    rows = [
        [btn("⬅️ К статистике", "adm:stats")],
    ]
    return "\n".join(lines), kb(*rows)


async def build_stats_groups(
    repo: RequestsRepo, page: int = 0, only: str = "",
) -> tuple[str, Keyboard]:
    """Все группы с числом студентов: раздельно, по размеру, по страницам.

    Раньше это был один плоский список вперемешку — вуз и колледж, в
    алфавитном порядке. Найти, где больше всего людей, было нельзя.
    """
    index = await groups_index(repo)
    vuz_n = sum(1 for g in index if is_vuz(g))
    college_n = len(index) - vuz_n
    total_users = sum(len(v) for v in index.values())

    # only пусто — все; «college»/«vuz» — одно подразделение.
    items = [(g, m) for g, m in index.items()
             if not only or is_vuz(g) == (only == "vuz")]
    items.sort(key=group_sort_key)

    pages = max(1, (len(items) + GROUPS_PER_PAGE - 1) // GROUPS_PER_PAGE)
    page = max(0, min(page, pages - 1))
    chunk = items[page * GROUPS_PER_PAGE:(page + 1) * GROUPS_PER_PAGE]

    rows = []
    for g, members in chunk:
        icon = "🏛" if is_vuz(g) else "🎓"
        sub = sum(1 for u in members if u.subscribed)
        rows.append([btn(f"{icon} {strip_unit(g)} — {len(members)} чел · 🔔 {sub}",
                         f"group_users:{g}")])

    # Переключатель подразделения — активное состояние видно по галочке.
    # «Без группы» в списки не попадает (группы нет), но это живые люди,
    # которые зашли и не выбрали ничего. Без отдельной кнопки их не найти.
    no_group = await repo.users.get_by_group(None)
    students_no_group = [u for u in no_group if u.role != "teacher"]
    if students_no_group:
        rows.append([btn(f"❓ Без группы — {len(students_no_group)}",
                         "group_users:__none__")])

    rows.append([
        btn(("✓ " if not only else "") + f"Все {len(index)}",
            "adm:stats:groups:all:0"),
        btn(("✓ " if only == "college" else "") + f"🎓 {college_n}",
            "adm:stats:groups:college:0"),
        btn(("✓ " if only == "vuz" else "") + f"🏛 {vuz_n}",
            "adm:stats:groups:vuz:0"),
    ])

    if pages > 1:
        nav = []
        if page > 0:
            nav.append(btn("◀️",
                           f"adm:stats:groups:{only or 'all'}:{page - 1}"))
        nav.append(btn(f"{page + 1} / {pages}",
                       f"adm:stats:groups:{only or 'all'}:{page}"))
        if page < pages - 1:
            nav.append(btn("▶️",
                           f"adm:stats:groups:{only or 'all'}:{page + 1}"))
        rows.append(nav)

    rows.append([btn("⬅️ К статистике", "adm:stats")])

    title = {"college": "🎓 Колледж", "vuz": "🏛 Вуз"}.get(only, "Все группы")
    lines = [
        f"👥 <b>{title}</b>",
        "",
        f"Групп: <b>{len(items)}</b> · студентов: <b>{sum(len(m) for _, m in items)}</b>",
        f"Всего по боту: {total_users} в {len(index)} группах",
        "",
        "Сортировка — по размеру, крупные сверху.",
        "Нажми на группу, чтобы увидеть состав.",
    ]
    return "\n".join(lines), kb(*rows)
