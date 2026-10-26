import datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, Message, ReplyKeyboardMarkup)

from common.schedule import (
    BELL_FULL,
    BELL_LABELS,
    BELL_OFF,
    BELL_ORDER,
    BELL_START_END,
    DETAIL_LABELS,
    DETAIL_ORDER,
    PARITY_EVEN,
    PARITY_ODD,
    bells_group,
    course_from_group,
    format_bell,
    format_day,
    format_no_lessons,
    format_not_published,
    format_stale_warning,
    format_teacher_results,
    format_unverified,
    format_week,
    is_vuz,
    strip_unit,
)
from infrastructure.database.models import User
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.services import source_state

# Названия для людей: в базе коды, студенту они ничего не говорят.
FACULTY_NAMES = {
    "FEU": "⚡ ФЭЭиУ",
    "GTF": "⛏ ГТФ",
}
FORM_NAMES = {
    "full": "Очная",
    "part": "Очно-заочная",
}

user_router = Router()

BACK_KB = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]
)

ROLE_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🎓 Студент", callback_data="role:student")],
    [InlineKeyboardButton(text="👨‍🏫 Преподаватель", callback_data="role:teacher")],
])

UNIT_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🏫 Колледж", callback_data="unit:college")],
    [InlineKeyboardButton(text="🎓 Вуз", callback_data="unit:vuz")],
    [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")],
])

COURSE_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="1 курс", callback_data="course:1"),
     InlineKeyboardButton(text="2 курс", callback_data="course:2")],
    [InlineKeyboardButton(text="3 курс", callback_data="course:3"),
     InlineKeyboardButton(text="4 курс", callback_data="course:4")],
    [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")],
])


class SubjectSearch(StatesGroup):
    waiting = State()


class TeacherSearch(StatesGroup):
    waiting = State()


class GroupSearch(StatesGroup):
    waiting = State()


def _is_teacher(user: User) -> bool:
    return user.role == "teacher"


def _has_identity(user: User) -> bool:
    return bool(user.teacher_name) if _is_teacher(user) else bool(user.group)


def _settings_text(user: User) -> str:
    """Экран настроек с примером того, что придёт при текущем режиме."""
    mode = user.bell_mode if user.bell_mode in BELL_PREVIEW else BELL_OFF
    return (f"⚙️ <b>Настройки</b>\n\n"
            f"Уведомления: <b>{BELL_LABELS.get(mode, 'выкл')}</b>\n"
            f"{BELL_PREVIEW[mode]}\n\n"
            f"Выбери действие 👇")

# Что именно придёт при каждом режиме. Показать пример дешевле, чем
# объяснять словами «звонок+конец пары» — человек не понимает разницу,
# пока не получит уведомление.
BELL_PREVIEW = {
    BELL_OFF: "<i>уведомления не приходят</i>",
    BELL_START_END: "🔔 1 пара · Математика · 204\n"
                    "🔔 Конец пары",
    BELL_FULL: "🔔 1 пара · Математика · 204\n"
               "🔔 Перемена\n"
               "🔔 Перемена закончилась\n"
               "🔔 Конец пары",
}


def _on_off(value: bool) -> str:
    return "вкл" if value else "выкл"


def menu_kb(user: User, support_link: str = "", is_editor: bool = False) -> InlineKeyboardMarkup:
    """Главное меню: только то, что нужно каждый день.

    Тонкие настройки (детализация звонков, режим уведомлений) убраны
    в «Настройки» — иначе меню разрастается до 8 рядов и в нём теряется
    главное действие.
    """
    sub_icon = "🔕" if user.subscribed else "🔔"

    rows = [
        [InlineKeyboardButton(text="📅 Сегодня", callback_data="day:today"),
         InlineKeyboardButton(text="📅 Завтра", callback_data="day:tomorrow")],
        [InlineKeyboardButton(text="🗓 Неделя", callback_data="week"),
         InlineKeyboardButton(text="📜 История", callback_data="hist")],
        [InlineKeyboardButton(text="🔎 Предмет", callback_data="find")],
        [InlineKeyboardButton(text="⏰ Звонки", callback_data="bell"),
         InlineKeyboardButton(text=f"{sub_icon} Подписка", callback_data="sub:toggle")],
    ]
    # Преподавателю «👥 Группа» не нужна: у него нет своей группы, и
    # кнопка показывала пары чужой группы, которую он никогда не выбирал.
    # Поиск по фамилии работает для обоих подразделений.
    if not _is_teacher(user):
        rows[2].append(InlineKeyboardButton(text="👨‍🏫 Преподаватель",
                                            callback_data="find_teacher"))
    if is_editor:
        rows.append([InlineKeyboardButton(text="✏️ Редактор расписания",
                                          callback_data="ed:back")])
    # Без идентичности остальные кнопки только ругаются «Сначала выбери
    # группу». Ставим выбор первым и заметным, чтобы новичок не тыкался.
    if not _has_identity(user):
        rows.insert(0, [InlineKeyboardButton(
            text="🎯 Выбрать группу" if not _is_teacher(user) else "🎯 Найти себя",
            callback_data="pick" if not _is_teacher(user) else "pick_teacher")])
    rows.append([InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")])
    if support_link:
        rows.append([InlineKeyboardButton(text="📨 Поддержка", url=support_link)])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_kb(user: User) -> InlineKeyboardMarkup:
    detail_label = DETAIL_LABELS.get(user.bell_detail, "кратко")
    bell_label = BELL_LABELS.get(user.bell_mode, "выкл")
    rows = []
    if _is_teacher(user):
        rows.append([InlineKeyboardButton(text="🎯 Сменить фамилию", callback_data="pick_teacher")])
    else:
        rows.append([InlineKeyboardButton(text="🎯 Сменить группу", callback_data="pick")])
        # Без группы менять нечего. У вуза курс зашит в номер группы
        # (ГИ-23 → 4 курс), поэтому кнопка ведёт к выбору другой группы
        # того же курса, а не переписывает поле.
        if user.group:
            rows.append([InlineKeyboardButton(text="🎯 Сменить курс", callback_data="pick_course")])
        rows.append([InlineKeyboardButton(text=f"🐱 Картинки: {_on_off(user.send_image)}",
                                          callback_data="image_toggle")])
    rows.append([InlineKeyboardButton(text=f"🕒 Детализация: {detail_label}",
                                      callback_data="detail")])
    rows.append([InlineKeyboardButton(text=f"🔔 Уведомления: {bell_label}",
                                      callback_data="bell_mode")])
    rows.append([InlineKeyboardButton(text="🎭 Сменить роль", callback_data="role_switch")])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def menu_text(user: User) -> str:
    if _is_teacher(user):
        if not (user.teacher_name or "").strip():
            return ("🎓 <b>Расписание ПТК</b>\n\n"
                    "Фамилия не выбрана.\n\nНайди себя в списке 👇")
        label, ident = "Преподаватель", user.teacher_name
    else:
        label = "Группа"
        # Суффикс @vuz — служебный, человеку его видеть незачем.
        if not user.group:
            # «не выбрана · 1 курс» читается как издевательство: курса
            # без группы не бывает, а кнопки дня всё равно откажут.
            return ("🎓 <b>Расписание ПТК</b>\n\n"
                    "Группа не выбрана.\n\nВыбери её, чтобы видеть расписание 👇")
        ident = strip_unit(user.group)
        if is_vuz(user.group):
            label = "Группа · вуз"
            # У вуза курс зашит в номер группы (ГИ-23 → 3 курс), и
            # отдельное поле course остаётся от прежней группы. Без
            # этого ГИ-23 подписывалась «1 курс».
            course = course_from_group(user.group)
        else:
            course = user.course
        if course:
            ident = f"{ident} · {course} курс"
    return f"🎓 <b>Расписание ПТК</b>\n\n{label}: <b>{ident}</b>\n\nВыбери действие 👇"


async def _render_menu(repo: RequestsRepo, user: User) -> tuple[str, InlineKeyboardMarkup]:
    s = await repo.settings.get_all()
    is_editor = bool(await repo.editors.get_group_for(user.id))
    return menu_text(user), menu_kb(user, s["support_link"], is_editor)


def _unit_kb() -> InlineKeyboardMarkup:
    """Первый шаг выбора — подразделение.

    У вуза и колледжа разные наборы групп и разные звонки. Показывать
    100+ групп одним списком значит заставить человека листать вслепую.
    """
    return UNIT_KB


async def _college_pick_kb(repo: RequestsRepo) -> InlineKeyboardMarkup:
    # college_lesson общая для обоих подразделений: там лежат и группы
    # вуза с суффиксом @vuz. Без фильтра в списке «Колледж» появлялись
    # 92 чужие группы — студент колледжа видел расписание вуза.
    groups = [g for g in await repo.college_lessons.get_groups()
              if not is_vuz(g)]
    buttons = [InlineKeyboardButton(text=g, callback_data=f"group:{g}") for g in groups]
    rows = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="pick")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _vuz_faculty_kb(repo: RequestsRepo) -> InlineKeyboardMarkup:
    """Факультеты вуза. Нужны, потому что по имени группы его не узнать."""
    groups = await repo.vuz_groups.all()
    facs = sorted({g.faculty for g in groups})
    rows = [[InlineKeyboardButton(text=FACULTY_NAMES.get(f, f),
                                  callback_data=f"vu:fac:{f}")] for f in facs]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="pick")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _vuz_form_kb(repo: RequestsRepo, faculty: str) -> InlineKeyboardMarkup:
    """Форма обучения внутри факультета."""
    groups = await repo.vuz_groups.all()
    forms = sorted({g.form for g in groups if g.faculty == faculty})
    rows = [[InlineKeyboardButton(text=FORM_NAMES.get(f, f),
                                  callback_data=f"vu:form:{faculty}:{f}")] for f in forms]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="unit:vuz")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _vuz_course_kb(repo: RequestsRepo, faculty: str, form: str) -> InlineKeyboardMarkup:
    courses = await repo.vuz_groups.courses(faculty, form)
    buttons = [InlineKeyboardButton(text=f"{c} курс",
                                    callback_data=f"vu:cr:{faculty}:{form}:{c}")
               for c in courses]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    # Экран курса рисуется и из «формы», и напрямую из факультета (когда
    # форма одна). Назад в обоих случаях — к факультету: вернуться на
    # экран формы, которого человек мог не видеть, хуже.
    rows.append([InlineKeyboardButton(text="⬅️ Назад",
                                      callback_data=f"vu:fac:{faculty}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _vuz_group_kb(repo: RequestsRepo, faculty: str, form: str,
                        course: int) -> InlineKeyboardMarkup:
    names = await repo.vuz_groups.by_course(faculty, form, course)
    buttons = [InlineKeyboardButton(text=strip_unit(n),
                                    callback_data=f"vu:g:{n}")
               for n in names]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    rows.append([InlineKeyboardButton(
        text="⬅️ Назад", callback_data=f"vu:form:{faculty}:{form}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# Преподавателей в расписании 235 (колледж) и 168 (вуз). Список кнопками
# в чате превращался в простыню на сотни строк, в которой вузовских не
# было вовсе. Вместо списка — подразделение и поиск по фамилии.
TEACHER_UNIT_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🏫 Колледж", callback_data="tunit:college")],
    [InlineKeyboardButton(text="🎓 Вуз", callback_data="tunit:vuz")],
    [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")],
])


async def _teacher_search_kb(repo: RequestsRepo, vuz: bool) -> InlineKeyboardMarkup:
    """Первые буквы фамилий вместо полного списка.

    Полный список не влезает в сообщение Telegram (4096 символов) и
    нечитаем на телефоне. По буквам человек добирается до своей фамилии
    за два нажатия.
    """
    names = (await repo.college_lessons.get_teachers_vuz() if vuz
             else await repo.college_lessons.get_teachers(vuz=False))
    letters = sorted({n[0].upper() for n in names if n})
    buttons = [InlineKeyboardButton(text=ch, callback_data=f"tlet:{'vuz' if vuz else 'col'}:{ch}")
               for ch in letters]
    rows = [buttons[i:i + 6] for i in range(0, len(buttons), 6)]
    # Назад — к выбору «колледж или вуз», а не сразу в список: иначе
    # человек, ошибшийся подразделением, должен начинать с нуля.
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="pick_teacher")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _teacher_letter_kb(repo: RequestsRepo, vuz: bool, letter: str) -> InlineKeyboardMarkup:
    names = (await repo.college_lessons.get_teachers_vuz() if vuz
             else await repo.college_lessons.get_teachers(vuz=False))
    picked = [n for n in names if n[:1].upper() == letter.upper()]
    buttons = [InlineKeyboardButton(text=n, callback_data=f"teacher:{n}") for n in picked]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    # Назад — к буквам того же подразделения. Раньше вело на выбор
    # «колледж/вуз» и заставляло заново выбирать букву.
    rows.append([InlineKeyboardButton(
        text="⬅️ Назад", callback_data=f"tunit:{'vuz' if vuz else 'college'}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _require_identity(cb: CallbackQuery, user: User) -> bool:
    if _has_identity(user):
        return True
    await cb.answer("Сначала выбери группу или фамилию 🎯")
    return False


async def _vuz_teacher_day(repo: RequestsRepo, user: User, date: datetime.date):
    """Пары преподавателя вуза на дату — из базового слоя вуза.

    Преподаватель может вести и колледж, и вуз: у вуза пары лежат в
    base_lesson со списком недель, у колледжа — в college_lesson.
    Поэтому источников два и они складываются.
    """
    from tgbot.services import sync_vuz
    anchor = await sync_vuz.get_anchor(repo)
    week = sync_vuz.vuz_week(date, anchor)
    # Чётность считаем здесь: репозиторий не должен знать правило
    # нумерации недель вуза. Без неё преподаватель видел пары чужой
    # недели — те, которых в этот день нет ни у одной группы.
    parity = PARITY_EVEN if week % 2 == 0 else PARITY_ODD
    rows = await repo.base_lessons.get_for_teacher(
        user.teacher_name, weekday=date.isoweekday(), week=week, parity=parity)
    return [_vuz_lesson_to_slot(r) for r in rows]


def _vuz_lesson_to_slot(lesson):
    """Привести пару вуза к виду, который понимает format_day.

    Группа нужна: по ней выбираются звонки (у вуза своя сетка, 8 пар
    до 22:00) и она же подписывает пару.
    """
    from tgbot.services.schedule_layer import Slot
    return Slot(lesson.para, lesson.subject, lesson.teacher, lesson.room,
                group=lesson.group)


async def _user_lessons(repo: RequestsRepo, user: User, date: datetime.date):
    if _is_teacher(user):
        college = await repo.college_lessons.get_for_teacher_date(user.teacher_name, date)
        vuz = await _vuz_teacher_day(repo, user, date)
        return sorted([*college, *vuz], key=lambda l: l.para)
    return await repo.college_lessons.get_for_group_date(user.group, date)


async def _user_lessons_range(repo: RequestsRepo, user: User, start: datetime.date, end: datetime.date):
    if _is_teacher(user):
        return await repo.college_lessons.get_for_teacher_range(user.teacher_name, start, end)
    return await repo.college_lessons.get_for_group_range(user.group, start, end)


async def _course_group_map(repo: RequestsRepo, user: User) -> dict[str, str] | None:
    if _is_teacher(user):
        m = await repo.users.get_group_course_map()
        return m or None
    cg = bells_group(user.group, user.course)
    return {user.group: cg} if cg else None


def _fmt(user: User, date: datetime.date, lessons, bell, lunches, gcg=None) -> str:
    """Текст дня для пользователя.

    ``meta`` был перевёрнут: студент видел преподавателя, а преподаватель
    — группу. Плюс преподавателю нужно склеивать поток: физкультура у
    шести групп — это одна пара, а не шесть.
    """
    is_teacher = _is_teacher(user)
    return format_day(
        date, lessons, bell, lunches, user.bell_detail,
        meta="group" if is_teacher else "teacher",
        show_rov=not is_teacher,
        group_course_group=gcg,
        merge_groups=is_teacher,
    )


@user_router.message(CommandStart())
async def start(message: Message, user: User, repo: RequestsRepo, state: FSMContext):
    await state.clear()
    if _has_identity(user):
        if not _is_teacher(user) and not user.course:
            await message.answer(
                f"🎓 Твоя группа: <b>{user.group}</b>\n\nНа каком ты курсе? 👇",
                reply_markup=COURSE_KB,
            )
        else:
            # Сразу показываем сегодняшний день — это то, за чем открывают бота.
            # Меню остаётся кнопкой под сообщением.
            await message.answer(await _day_text(repo, user, datetime.date.today()),
                                 reply_markup=BOTTOM_KB)
            text, kb = await _render_menu(repo, user)
            await message.answer(text, reply_markup=kb)
    else:
        await message.answer("🎓 Привет! Кто ты?", reply_markup=ROLE_KB)


@user_router.message(Command("group"))
async def set_group_cmd(message: Message, repo: RequestsRepo, user: User):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Формат: /group ТЭ-26ФП")
        return
    group = parts[1].strip().upper()
    await repo.users.set_role(user.id, "student")
    await repo.users.set_group(user.id, group)
    user.role = "student"
    user.group = group
    if user.course:
        text, kb = await _render_menu(repo, user)
        await message.answer(f"Твоя группа: <b>{group}</b>\n\n{text}", reply_markup=kb)
    else:
        await message.answer(f"Твоя группа: <b>{group}</b>\n\nНа каком ты курсе? 👇", reply_markup=COURSE_KB)


@user_router.callback_query(F.data == "role:student")
async def cb_role_student(cb: CallbackQuery, repo: RequestsRepo, user: User):
    await repo.users.set_role(user.id, "student")
    await cb.message.edit_text("🎓 Где ты учишься?", reply_markup=_unit_kb())
    await cb.answer()


@user_router.callback_query(F.data == "role:teacher")
async def cb_role_teacher(cb: CallbackQuery, repo: RequestsRepo, user: User):
    await repo.users.set_role(user.id, "teacher")
    await cb.message.edit_text("👨‍🏫 Где ты преподаёшь?", reply_markup=TEACHER_UNIT_KB)
    await cb.answer()


@user_router.callback_query(F.data == "role_switch")
async def cb_role_switch(cb: CallbackQuery, repo: RequestsRepo, user: User):
    await repo.users.set_group(user.id, None)
    await repo.users.set_teacher_name(user.id, None)
    await repo.users.set_course(user.id, None)
    await repo.users.set_unit(user.id, "college")
    await cb.message.edit_text("🎓 Кто ты?", reply_markup=ROLE_KB)
    await cb.answer()


@user_router.callback_query(F.data == "pick")
async def cb_pick(cb: CallbackQuery, repo: RequestsRepo):
    await cb.message.edit_text("🎓 Где ты учишься?", reply_markup=_unit_kb())
    await cb.answer()


@user_router.callback_query(F.data == "unit:college")
async def cb_unit_college(cb: CallbackQuery, repo: RequestsRepo):
    await cb.message.edit_text("🏫 Выбери свою группу 👇",
                               reply_markup=await _college_pick_kb(repo))
    await cb.answer()


@user_router.callback_query(F.data == "unit:vuz")
async def cb_unit_vuz(cb: CallbackQuery, repo: RequestsRepo):
    kb = await _vuz_faculty_kb(repo)
    if len(kb.inline_keyboard) == 1:
        # Групп вуза ещё нет — не показываем пустой экран.
        await cb.answer("Расписание вуза пока не загружено", show_alert=True)
        return
    await cb.message.edit_text("🎓 Выбери факультет 👇", reply_markup=kb)
    await cb.answer()


@user_router.callback_query(F.data.startswith("vu:fac:"))
async def cb_vuz_faculty(cb: CallbackQuery, repo: RequestsRepo):
    faculty = cb.data.split(":")[2]
    forms = sorted({g.form for g in await repo.vuz_groups.all()
                    if g.faculty == faculty})
    # Одна форма — незачем спрашивать, сразу курсы.
    if len(forms) == 1:
        await cb.message.edit_text(
            f"{FACULTY_NAMES.get(faculty, faculty)}\n\nВыбери курс 👇",
            reply_markup=await _vuz_course_kb(repo, faculty, forms[0]))
        await cb.answer()
        return
    await cb.message.edit_text(
        f"{FACULTY_NAMES.get(faculty, faculty)}\n\nВыбери форму обучения 👇",
        reply_markup=await _vuz_form_kb(repo, faculty))
    await cb.answer()


@user_router.callback_query(F.data.startswith("vu:form:"))
async def cb_vuz_form(cb: CallbackQuery, repo: RequestsRepo):
    _, _, faculty, form = cb.data.split(":")
    await cb.message.edit_text(
        f"{FACULTY_NAMES.get(faculty, faculty)} · {FORM_NAMES.get(form, form)}\n\n"
        f"Выбери курс 👇",
        reply_markup=await _vuz_course_kb(repo, faculty, form))
    await cb.answer()


@user_router.callback_query(F.data.startswith("vu:cr:"))
async def cb_vuz_course(cb: CallbackQuery, repo: RequestsRepo):
    _, _, faculty, form, course = cb.data.split(":")
    await cb.message.edit_text(
        f"{FACULTY_NAMES.get(faculty, faculty)} · {FORM_NAMES.get(form, form)}"
        f" · {course} курс\n\nВыбери группу 👇",
        reply_markup=await _vuz_group_kb(repo, faculty, form, int(course)))
    await cb.answer()


@user_router.callback_query(F.data.startswith("vu:g:"))
async def cb_vuz_group(cb: CallbackQuery, repo: RequestsRepo, user: User):
    """Группа вуза выбрана. Курс берём из справочника, не угадываем."""
    name = cb.data[5:]
    info = await repo.vuz_groups.get(name)
    await repo.users.set_role(user.id, "student")
    await repo.users.set_group(user.id, name)
    await repo.users.set_unit(user.id, "vuz")
    course = info.course if info else None
    if course:
        await repo.users.set_course(user.id, course)
    user.role = "student"
    user.group = name
    user.unit = "vuz"
    user.course = course
    text, kb = await _render_menu(repo, user)
    await cb.message.edit_text(
        f"🎓 Твоя группа: <b>{strip_unit(name)}</b>"
        f"\nВуз · {FACULTY_NAMES.get(info.faculty, info.faculty) if info else ''}"
        f"\n\n{text}", reply_markup=kb)
    await cb.answer(f"{strip_unit(name)}")


@user_router.callback_query(F.data == "pick_teacher")
async def cb_pick_teacher(cb: CallbackQuery, repo: RequestsRepo):
    await cb.message.edit_text("👨‍🏫 Где ты преподаёшь?", reply_markup=TEACHER_UNIT_KB)
    await cb.answer()


@user_router.callback_query(F.data == "pick_course")
async def cb_pick_course(cb: CallbackQuery, repo: RequestsRepo, user: User):
    """Смена курса.

    У колледжа курс — отдельное поле: он выбирает поток звонков (1 и 4
    против 2 и 3). У вуза курс зашит в номер группы, поэтому меняется
    выбором группы того же курса: иначе подпись разошлась бы с фактом.
    """
    info = await repo.vuz_groups.get(user.group) if is_vuz(user.group) else None
    if info is None:
        await cb.message.edit_text("На каком ты курсе? 👇", reply_markup=COURSE_KB)
        await cb.answer()
        return

    courses = await repo.vuz_groups.courses(info.faculty, info.form)
    buttons = [InlineKeyboardButton(
        text=f"{c} курс", callback_data=f"vu:cr:{info.faculty}:{info.form}:{c}")
        for c in courses]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="settings")])
    await cb.message.edit_text(
        f"Сейчас {info.course} курс. На какой перевести? 👇",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


@user_router.callback_query(F.data == "settings")
async def cb_settings(cb: CallbackQuery, user: User, repo: RequestsRepo, state: FSMContext):
    await state.clear()
    await cb.message.edit_text(_settings_text(user), reply_markup=settings_kb(user))
    await cb.answer()


@user_router.callback_query(F.data.startswith("group:"))
async def cb_group(cb: CallbackQuery, repo: RequestsRepo, user: User):
    group = cb.data.split(":", 1)[1]
    await repo.users.set_role(user.id, "student")
    await repo.users.set_group(user.id, group)
    await repo.users.set_unit(user.id, "college")
    user.role = "student"
    user.group = group
    user.unit = "college"
    if user.course:
        text, kb = await _render_menu(repo, user)
        await cb.message.edit_text(f"Твоя группа: <b>{group}</b>\n\n{text}", reply_markup=kb)
    else:
        await cb.message.edit_text(f"Твоя группа: <b>{group}</b>\n\nНа каком ты курсе? 👇", reply_markup=COURSE_KB)
    await cb.answer(f"Группа {group}")


@user_router.callback_query(F.data.startswith("course:"))
async def cb_course(cb: CallbackQuery, repo: RequestsRepo, user: User):
    course = int(cb.data.split(":", 1)[1])
    await repo.users.set_course(user.id, course)
    user.course = course
    text, kb = await _render_menu(repo, user)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer(f"{course} курс")


@user_router.callback_query(F.data.startswith("tunit:"))
async def cb_teacher_unit(cb: CallbackQuery, repo: RequestsRepo):
    vuz = cb.data.split(":", 1)[1] == "vuz"
    where = "вуза" if vuz else "колледжа"
    await cb.message.edit_text(
        f"👨‍🏫 Преподаватели {where}\n\nВыбери первую букву фамилии 👇",
        reply_markup=await _teacher_search_kb(repo, vuz))
    await cb.answer()


@user_router.callback_query(F.data.startswith("tlet:"))
async def cb_teacher_letter(cb: CallbackQuery, repo: RequestsRepo):
    _, unit, letter = cb.data.split(":", 2)
    vuz = unit == "vuz"
    await cb.message.edit_text(
        f"👨‍🏫 Фамилии на «{letter}»\n\nВыбери себя 👇",
        reply_markup=await _teacher_letter_kb(repo, vuz, letter))
    await cb.answer()


@user_router.callback_query(F.data.startswith("teacher:"))
async def cb_teacher(cb: CallbackQuery, repo: RequestsRepo, user: User):
    name = cb.data.split(":", 1)[1]
    await repo.users.set_role(user.id, "teacher")
    await repo.users.set_teacher_name(user.id, name)
    text, kb = await _render_menu(repo, user)
    await cb.message.edit_text(f"Преподаватель: <b>{name}</b>\n\n{text}", reply_markup=kb)
    await cb.answer(name)


@user_router.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery, user: User, repo: RequestsRepo, state: FSMContext):
    await state.clear()
    text, kb = await _render_menu(repo, user)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


async def _day_text(repo: RequestsRepo, user: User, date: datetime.date) -> str:
    bell, lunches = await repo.bell_schedule.get_context()
    gcg = await _course_group_map(repo, user)
    lessons = await _user_lessons(repo, user, date)

    # Замены могли не доехать, если сайт лежит. Постоянное расписание при
    # этом верное, поэтому не скрываем его — только предупреждаем.
    # У вуза свой источник: сайт колледжа может лежать, а расписание вуза
    # при этом свежее. Общий флаг показывал студенту вуза чужую проблему.
    if is_vuz(user.group):
        stale = await source_state.is_stale_vuz(repo)
        last_ok = await source_state.last_ok_vuz(repo) if stale else None
    else:
        stale = await source_state.is_stale(repo)
        last_ok = await source_state.last_ok(repo) if stale else None

    if lessons:
        text = _fmt(user, date, lessons, bell, lunches, gcg)
        # Если сайт ещё ни разу не опрашивался (свежий запуск), не пугаем
        # предупреждением на каждом экране — оно появится, если опрос
        # действительно не пройдёт. Расписание и так есть.
        if stale and last_ok is not None:
            text += format_stale_warning(last_ok)
    else:
        note = None
        if not _is_teacher(user):
            note = await repo.no_lessons.get_note(date, user.group)
        published = await repo.schedule_files.get_hash(date) is not None
        if note:
            text = format_no_lessons(date, note)
        elif published:
            # День был опубликован — значит на момент публикации пар не было.
            text = format_no_lessons(date)
            if stale:
                text += format_stale_warning(last_ok)
        elif stale:
            # Ни пары, ни публикации, ни связи с сайтом — утверждать
            # «занятий нет» нельзя.
            text = format_unverified(date, last_ok)
        else:
            s = await repo.settings.get_all()
            deadline = int(s.get("deadline_hour", 20) or 20)
            now = datetime.datetime.now()
            if 0 <= deadline <= 23 and now.hour >= deadline:
                text = format_no_lessons(date)
            else:
                text = format_not_published(date)
        for i in range(1, 8):
            d = date + datetime.timedelta(days=i)
            nxt = await _user_lessons(repo, user, d)
            if nxt:
                text += "\n\nБлижайшее —\n" + _fmt(user, d, nxt, bell, lunches, gcg)
                break
    return text


async def _show_day(cb: CallbackQuery, repo: RequestsRepo, user: User, date: datetime.date):
    await cb.message.edit_text(await _day_text(repo, user, date), reply_markup=BACK_KB)
    await cb.answer()


@user_router.callback_query(F.data == "day:today")
async def cb_today(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_identity(cb, user):
        return
    await _show_day(cb, repo, user, datetime.date.today())


@user_router.callback_query(F.data == "day:tomorrow")
async def cb_tomorrow(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_identity(cb, user):
        return
    await _show_day(cb, repo, user, datetime.date.today() + datetime.timedelta(days=1))


async def _week_text(repo: RequestsRepo, user: User) -> str:
    bell, lunches = await repo.bell_schedule.get_context()
    gcg = await _course_group_map(repo, user)
    start = datetime.date.today()
    end = start + datetime.timedelta(days=6)
    lessons = await _user_lessons_range(repo, user, start, end)
    by_date: dict[datetime.date, list] = {}
    for l in lessons:
        by_date.setdefault(l.date, []).append(l)
    entries = [(d, by_date[d]) for d in sorted(by_date)]
    meta = "group" if _is_teacher(user) else "teacher"
    show_rov = not _is_teacher(user)
    return format_week(entries, bell, lunches, user.bell_detail, meta, show_rov, gcg)


@user_router.callback_query(F.data == "week")
async def cb_week(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_identity(cb, user):
        return
    await cb.message.edit_text(await _week_text(repo, user), reply_markup=BACK_KB)
    await cb.answer()


@user_router.callback_query(F.data == "bell")
async def cb_bell(cb: CallbackQuery, repo: RequestsRepo, user: User):
    """Сетка звонков — своя для каждого подразделения.

    Раньше экран всегда показывал колледж: студент и преподаватель вуза
    видели «Разговоры о важном», деление на курсы и 5 пар вместо 8.
    """
    bell, lunches = await repo.bell_schedule.get_context()
    is_vuz_user = (is_vuz(user.group) if user.group
                   else user.unit == "vuz")
    await cb.message.edit_text(format_bell(bell, lunches, vuz=is_vuz_user),
                               reply_markup=BACK_KB)
    await cb.answer()


HIST_PAGE = 5


async def _hist_page(repo: RequestsRepo, user: User, before: datetime.date | None) -> tuple[str, InlineKeyboardMarkup]:
    """Окно из пяти дат, начиная с самой свежей раньше ``before``.

    Курсор лежит в callback_data, а не в FSM: переживает рестарт и не
    путается, если человек листает с двух устройств.
    """
    if _is_teacher(user):
        dates = await repo.college_lessons.get_dates_for_teacher(user.teacher_name)
    else:
        dates = await repo.college_lessons.get_dates_for_group(user.group)
    past = sorted((d for d in dates if d < datetime.date.today()), reverse=True)
    if before:
        past = [d for d in past if d < before]

    if not past:
        # У вуза история короче: college_lesson материализуется вперёд на
        # 14 дней, а назад заполняется только по мере прошествия. Поэтому
        # «Больше расписания нет» на первом заходе — норма, а не ошибка.
        # Говорим это прямо, иначе выглядит как поломка.
        text = ("📜 <b>История расписания</b>\n\n"
                "Прошедших дней пока нет — они копятся по мере учёбы.")
        return text, InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]])

    window = past[:HIST_PAGE]
    buttons = [InlineKeyboardButton(text=f"{d.day:02d}.{d.month:02d}",
                                    callback_data=f"hist:{d.isoformat()}")
               for d in window]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    if len(past) > HIST_PAGE:
        rows.append([InlineKeyboardButton(
            text="⬅️ Раньше", callback_data=f"histpage:{window[-1].isoformat()}")])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")])
    return "📜 История расписания\n\nВыбери дату 👇", InlineKeyboardMarkup(inline_keyboard=rows)


@user_router.callback_query(F.data == "hist")
async def cb_hist(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_identity(cb, user):
        return
    text, kb = await _hist_page(repo, user, None)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@user_router.callback_query(F.data.startswith("histpage:"))
async def cb_hist_page(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_identity(cb, user):
        return
    before = datetime.date.fromisoformat(cb.data.split(":", 1)[1])
    text, kb = await _hist_page(repo, user, before)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@user_router.callback_query(F.data.startswith("hist:"))
async def cb_hist_date(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_identity(cb, user):
        return
    date = datetime.date.fromisoformat(cb.data.split(":", 1)[1])
    bell, lunches = await repo.bell_schedule.get_context()
    gcg = await _course_group_map(repo, user)
    lessons = await _user_lessons(repo, user, date)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К истории", callback_data="hist")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")],
    ])
    await cb.message.edit_text(_fmt(user, date, lessons, bell, lunches, gcg), reply_markup=kb)
    await cb.answer()


@user_router.callback_query(F.data == "sub:toggle")
async def cb_sub(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_identity(cb, user):
        return
    new = not user.subscribed
    await repo.users.set_subscribed(user.id, new)
    text, kb = await _render_menu(repo, user)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer("Подписка включена 🔔" if new else "Подписка отключена 🔕")


@user_router.callback_query(F.data == "bell_mode")
async def cb_bell_mode(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_identity(cb, user):
        return
    cur = user.bell_mode if user.bell_mode in BELL_ORDER else BELL_ORDER[0]
    nxt = BELL_ORDER[(BELL_ORDER.index(cur) + 1) % len(BELL_ORDER)]
    await repo.users.set_bell_mode(user.id, nxt)
    user.bell_mode = nxt
    await cb.message.edit_text(_settings_text(user), reply_markup=settings_kb(user))
    await cb.answer(f"Звонки: {BELL_LABELS[nxt]}")


@user_router.callback_query(F.data == "image_toggle")
async def cb_image_toggle(cb: CallbackQuery, repo: RequestsRepo, user: User):
    new = not user.send_image
    await repo.users.set_send_image(user.id, new)
    user.send_image = new
    await cb.message.edit_text(_settings_text(user), reply_markup=settings_kb(user))
    await cb.answer("Картинки включены 🐱" if new else "Картинки отключены")


@user_router.callback_query(F.data == "detail")
async def cb_detail(cb: CallbackQuery, repo: RequestsRepo, user: User):
    cur = user.bell_detail if user.bell_detail in DETAIL_ORDER else DETAIL_ORDER[0]
    nxt = DETAIL_ORDER[(DETAIL_ORDER.index(cur) + 1) % len(DETAIL_ORDER)]
    await repo.users.set_bell_detail(user.id, nxt)
    user.bell_detail = nxt
    await cb.message.edit_text(_settings_text(user), reply_markup=settings_kb(user))
    await cb.answer(f"Детализация: {DETAIL_LABELS[nxt]}")


@user_router.callback_query(F.data == "find")
async def cb_find(cb: CallbackQuery, user: User, state: FSMContext):
    if not await _require_identity(cb, user):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Отмена", callback_data="find:cancel")],
    ])
    await cb.message.edit_text("🔎 Напиши название предмета (например, «химия»):", reply_markup=kb)
    await state.set_state(SubjectSearch.waiting)
    await cb.answer()


@user_router.callback_query(F.data == "find:cancel")
async def cb_find_cancel(cb: CallbackQuery, user: User, repo: RequestsRepo, state: FSMContext):
    await state.clear()
    text, kb = await _render_menu(repo, user)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@user_router.message(SubjectSearch.waiting)
async def subject_answer(message: Message, repo: RequestsRepo, user: User, state: FSMContext):
    await state.clear()
    subj = message.text.strip()
    if _is_teacher(user):
        lessons = await repo.college_lessons.get_all_for_teacher(user.teacher_name)
    else:
        lessons = await repo.college_lessons.get_all_for_group(user.group)
    matched = [l for l in lessons if subj.casefold() in l.subject.casefold()]
    if not matched:
        await message.answer(f"По «{subj}» ничего не нашлось", reply_markup=BACK_KB)
        return
    results = matched[:5]
    bell, lunches = await repo.bell_schedule.get_context()
    gcg = await _course_group_map(repo, user)
    by_date: dict[datetime.date, list] = {}
    for l in results:
        by_date.setdefault(l.date, []).append(l)
    parts = [_fmt(user, d, by_date[d], bell, lunches, gcg) for d in sorted(by_date, reverse=True)]
    await message.answer(f"🔎 «{subj}» — последние занятия:\n\n" + "\n\n".join(parts), reply_markup=BACK_KB)


@user_router.callback_query(F.data == "find_teacher")
async def cb_find_teacher(cb: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Отмена", callback_data="find:cancel")],
    ])
    await cb.message.edit_text("👨‍🏫 Напиши фамилию преподавателя:", reply_markup=kb)
    await state.set_state(TeacherSearch.waiting)
    await cb.answer()


@user_router.message(TeacherSearch.waiting)
async def teacher_answer(message: Message, repo: RequestsRepo, state: FSMContext):
    await state.clear()
    q = message.text.strip()
    lessons = await repo.college_lessons.get_all_lessons()
    matched = [l for l in lessons if q.casefold() in (l.teacher or "").casefold()]
    if not matched:
        await message.answer(f"Преподаватель «{q}» не найден", reply_markup=BACK_KB)
        return
    today = datetime.date.today()
    week_end = today + datetime.timedelta(days=6)
    upcoming = [l for l in matched if today <= l.date <= week_end]
    scope = upcoming if upcoming else matched[-12:]
    bell, lunches = await repo.bell_schedule.get_context()
    by_date: dict[datetime.date, list] = {}
    for l in scope:
        by_date.setdefault(l.date, []).append(l)
    entries = [(d, by_date[d]) for d in sorted(by_date)]
    await message.answer(
        f"👨‍🏫 «{q}»:\n\n" + format_teacher_results(entries, bell, lunches),
        reply_markup=BACK_KB,
    )


@user_router.callback_query(F.data == "find_group")
async def cb_find_group(cb: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Отмена", callback_data="find:cancel")],
    ])
    await cb.message.edit_text("👥 Напиши номер группы (например, ДП-26):", reply_markup=kb)
    await state.set_state(GroupSearch.waiting)
    await cb.answer()


@user_router.message(GroupSearch.waiting)
async def group_answer(message: Message, repo: RequestsRepo, state: FSMContext):
    await state.clear()
    group = message.text.strip().upper()
    bell, lunches = await repo.bell_schedule.get_context()
    start = datetime.date.today()
    end = start + datetime.timedelta(days=6)
    lessons = await repo.college_lessons.get_for_group_range(group, start, end)
    if not lessons:
        await message.answer(f"У группы «{group}» пар на неделю нет", reply_markup=BACK_KB)
        return
    by_date: dict[datetime.date, list] = {}
    for l in lessons:
        by_date.setdefault(l.date, []).append(l)
    entries = [(d, by_date[d]) for d in sorted(by_date)]
    await message.answer(
        f"👥 «{group}» — неделя:\n\n" + format_teacher_results(entries, bell, lunches),
        reply_markup=BACK_KB,
    )


# Нижнее меню: три кнопки, которые нужны каждый день. Reply-клавиатура
# всегда на экране, целиться в инлайн-кнопку под сообщением не надо.
# Обработчики стоят ДО any_text — иначе он их перехватит.
BOTTOM_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📅 Сегодня"),
               KeyboardButton(text="📅 Завтра"),
               KeyboardButton(text="🗓 Неделя")]],
    resize_keyboard=True,
    is_persistent=True,
)


@user_router.message(F.text == "📅 Сегодня")
async def btn_today(message: Message, repo: RequestsRepo, user: User):
    if not _has_identity(user):
        await message.answer("Сначала выбери группу или фамилию 🎯", reply_markup=ROLE_KB)
        return
    await message.answer(await _day_text(repo, user, datetime.date.today()),
                         reply_markup=BACK_KB)


@user_router.message(F.text == "📅 Завтра")
async def btn_tomorrow(message: Message, repo: RequestsRepo, user: User):
    if not _has_identity(user):
        await message.answer("Сначала выбери группу или фамилию 🎯", reply_markup=ROLE_KB)
        return
    await message.answer(
        await _day_text(repo, user, datetime.date.today() + datetime.timedelta(days=1)),
        reply_markup=BACK_KB)


@user_router.message(F.text == "🗓 Неделя")
async def btn_week(message: Message, repo: RequestsRepo, user: User):
    if not _has_identity(user):
        await message.answer("Сначала выбери группу или фамилию 🎯", reply_markup=ROLE_KB)
        return
    await message.answer(await _week_text(repo, user), reply_markup=BACK_KB)


@user_router.message(F.text, ~F.text.startswith("/"))
async def any_text(message: Message, repo: RequestsRepo, user: User):
    """Не молчим на непонятный текст — показываем меню и нижние кнопки."""
    text, kb = await _render_menu(repo, user)
    await message.answer(text, reply_markup=kb)
    await message.answer("Кнопки внизу — быстрый доступ 👇", reply_markup=BOTTOM_KB)
