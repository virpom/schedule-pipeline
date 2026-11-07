"""Клавиатуры меню и выбора — как данные, без Telegram.

Перенесено из ``tgbot/handlers/user.py`` на этапе 1 (план 173).
Функции возвращают ``Keyboard`` из ``core.keyboard``; адаптер
``tgbot/adapters/keyboard.py`` превращает её в телеграмную.

Проверено: 26 клавиатур во всех вариантах пользователя (студент,
студент вуза, преподаватель, без группы, без фамилии, с редактором и
без) дают ту же раскладку, тексты и действия, что до переноса.
"""
from __future__ import annotations

from common.schedule import (BELL_LABELS, DETAIL_LABELS, is_vuz,
                             strip_unit)
from core.day import has_identity, is_teacher
from core.keyboard import Keyboard, btn, kb
from infrastructure.database.models import User
from infrastructure.database.repo.requests import RequestsRepo

# Названия для людей: в базе коды, студенту они ничего не говорят.
FACULTY_NAMES = {
    "FEU": "⚡ ФЭЭиУ",
    "GTF": "⛏ ГТФ",
}
FORM_NAMES = {
    "full": "Очная",
    "part": "Очно-заочная",
}

def _on_off(value: bool) -> str:
    return "вкл" if value else "выкл"


def unit_kb() -> Keyboard:
    """Первый шаг выбора — подразделение.

    У вуза и колледжа разные наборы групп и разные звонки. Показывать
    100+ групп одним списком значит заставить человека листать вслепую.
    """
    return kb([btn("🏫 Колледж", "unit:college")],
              [btn("🎓 Вуз", "unit:vuz")],
              [btn("⬅️ В меню", "menu")])


def menu_kb(user: User, support_link: str = "",
            is_editor: bool = False) -> Keyboard:
    """Главное меню: только то, что нужно каждый день.

    Тонкие настройки (детализация звонков, режим уведомлений) убраны
    в «Настройки» — иначе меню разрастается до 8 рядов и в нём теряется
    главное действие.
    """
    sub_icon = "🔕" if user.subscribed else "🔔"

    rows = [
        [btn("📅 Сегодня", "day:today"), btn("📅 Завтра", "day:tomorrow")],
        [btn("🗓 7 дней", "week"), btn("📜 История", "hist")],
        [btn("🔎 Предмет", "find")],
        [btn("⏰ Звонки", "bell"), btn(f"{sub_icon} Подписка", "sub:toggle")],
    ]
    # Преподавателю «👥 Группа» не нужна: у него нет своей группы, и
    # кнопка показывала пары чужой группы, которую он никогда не выбирал.
    # Поиск по фамилии работает для обоих подразделений.
    if not is_teacher(user):
        rows[2].append(btn("👨‍🏫 Преподаватель", "find_teacher"))
    if is_editor:
        rows.append([btn("✏️ Редактор расписания", "ed:back")])
    # Без идентичности остальные кнопки только ругаются «Сначала выбери
    # группу». Ставим выбор первым и заметным, чтобы новичок не тыкался.
    if not has_identity(user):
        rows.insert(0, [btn("🎯 Выбрать группу" if not is_teacher(user)
                            else "🎯 Найти себя",
                            "pick" if not is_teacher(user) else "pick_teacher")])
    rows.append([btn("⚙️ Настройки", "settings")])
    if support_link:
        rows.append([btn("📨 Поддержка", url=support_link)])
    return kb(*rows)


def settings_kb(user: User) -> Keyboard:
    detail_label = DETAIL_LABELS.get(user.bell_detail, "кратко")
    bell_label = BELL_LABELS.get(user.bell_mode, "выкл")
    rows = []
    if is_teacher(user):
        rows.append([btn("🎯 Сменить фамилию", "pick_teacher")])
    else:
        rows.append([btn("🎯 Сменить группу", "pick")])
        # Без группы менять нечего. У вуза курс зашит в номер группы
        # (ГИ-23 → 4 курс), поэтому кнопка ведёт к выбору другой группы
        # того же курса, а не переписывает поле.
        if user.group:
            rows.append([btn("🎯 Сменить курс", "pick_course")])
        rows.append([btn(f"🐱 Картинки: {_on_off(user.send_image)}",
                         "image_toggle")])
    rows.append([btn(f"🕒 Детализация: {detail_label}", "detail")])
    rows.append([btn(f"🔔 Уведомления: {bell_label}", "bell_mode")])
    rows.append([btn("🎭 Сменить роль", "role_switch")])
    rows.append([btn("🏠 Главное меню", "menu")])
    return kb(*rows)


async def college_pick_kb(repo: RequestsRepo) -> Keyboard:
    # college_lesson общая для обоих подразделений: там лежат и группы
    # вуза с суффиксом @vuz. Без фильтра в списке «Колледж» появлялись
    # 92 чужие группы — студент колледжа видел расписание вуза.
    groups = [g for g in await repo.college_lessons.get_groups()
              if not is_vuz(g)]
    buttons = [btn(g, f"group:{g}") for g in groups]
    rows = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
    rows.append([btn("⬅️ Назад", "pick")])
    return kb(*rows)


async def vuz_faculty_kb(repo: RequestsRepo) -> Keyboard:
    """Факультеты вуза. Нужны, потому что по имени группы его не узнать."""
    groups = await repo.vuz_groups.all()
    facs = sorted({g.faculty for g in groups})
    rows = [[btn(FACULTY_NAMES.get(f, f), f"vu:fac:{f}")] for f in facs]
    rows.append([btn("⬅️ Назад", "pick")])
    return kb(*rows)


async def vuz_form_kb(repo: RequestsRepo, faculty: str) -> Keyboard:
    """Форма обучения внутри факультета."""
    groups = await repo.vuz_groups.all()
    forms = sorted({g.form for g in groups if g.faculty == faculty})
    rows = [[btn(FORM_NAMES.get(f, f), f"vu:form:{faculty}:{f}")] for f in forms]
    rows.append([btn("⬅️ Назад", "unit:vuz")])
    return kb(*rows)


async def vuz_course_kb(repo: RequestsRepo, faculty: str,
                        form: str) -> Keyboard:
    courses = await repo.vuz_groups.courses(faculty, form)
    buttons = [btn(f"{c} курс", f"vu:cr:{faculty}:{form}:{c}") for c in courses]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    # Экран курса рисуется и из «формы», и напрямую из факультета (когда
    # форма одна). Назад в обоих случаях — к факультету: вернуться на
    # экран формы, которого человек мог не видеть, хуже.
    rows.append([btn("⬅️ Назад", f"vu:fac:{faculty}")])
    return kb(*rows)


async def vuz_group_kb(repo: RequestsRepo, faculty: str, form: str,
                       course: int) -> Keyboard:
    names = await repo.vuz_groups.by_course(faculty, form, course)
    buttons = [btn(strip_unit(n), f"vu:g:{n}") for n in names]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    rows.append([btn("⬅️ Назад", f"vu:form:{faculty}:{form}")])
    return kb(*rows)


# Преподавателей в расписании 235 (колледж) и 168 (вуз). Список кнопками
# в чате превращался в простыню на сотни строк, в которой вузовских не
# было вовсе. Вместо списка — подразделение и поиск по фамилии.
def teacher_unit_kb() -> Keyboard:
    return kb([btn("🏫 Колледж", "tunit:college")],
              [btn("🎓 Вуз", "tunit:vuz")],
              [btn("⬅️ В меню", "menu")])


async def teacher_search_kb(repo: RequestsRepo, vuz: bool) -> Keyboard:
    """Первые буквы фамилий вместо полного списка.

    Полный список не влезает в сообщение Telegram (4096 символов) и
    нечитаем на телефоне. По буквам человек добирается до своей фамилии
    за два нажатия.
    """
    names = (await repo.college_lessons.get_teachers_vuz() if vuz
             else await repo.college_lessons.get_teachers(vuz=False))
    letters = sorted({n[0].upper() for n in names if n})
    buttons = [btn(ch, f"tlet:{'vuz' if vuz else 'col'}:{ch}") for ch in letters]
    rows = [buttons[i:i + 6] for i in range(0, len(buttons), 6)]
    # Назад — к выбору «колледж или вуз», а не сразу в список: иначе
    # человек, ошибшийся подразделением, должен начинать с нуля.
    rows.append([btn("⬅️ Назад", "pick_teacher")])
    return kb(*rows)


async def teacher_letter_kb(repo: RequestsRepo, vuz: bool,
                            letter: str) -> Keyboard:
    names = (await repo.college_lessons.get_teachers_vuz() if vuz
             else await repo.college_lessons.get_teachers(vuz=False))
    picked = [n for n in names if n[:1].upper() == letter.upper()]
    buttons = [btn(n, f"teacher:{n}") for n in picked]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    # Назад — к буквам того же подразделения. Раньше вело на выбор
    # «колледж/вуз» и заставляло заново выбирать букву.
    rows.append([btn("⬅️ Назад",
                     f"tunit:{'vuz' if vuz else 'college'}")])
    return kb(*rows)
