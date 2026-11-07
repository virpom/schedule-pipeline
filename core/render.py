"""Текст экранов из данных. Вся разметка бота — здесь.

Почему отдельно: MAX принимает ``format: "html"`` с теми же тегами
(``<b>``, ``<i>``, ``<s>``, ``<code>``), что и Telegram. Значит один
рендерер обслуживает обе платформы, и второй бот не нуждается в своём
слое оформления.

Правило: этот модуль не ходит в базу. На вход — ``DayView``, на выход —
строка. Так его можно проверить без базы и без сети.
"""
from __future__ import annotations

from common.schedule import (BELL_FULL, BELL_LABELS, BELL_OFF,
                             BELL_START_END, format_day,
                             format_no_lessons, format_not_published,
                             format_stale_warning, format_unverified)
from core.day import DayView

NO_IDENTITY = ("🎯 <b>Сначала выбери группу</b>\n\n"
               "Пока бот не знает, где ты учишься, расписания у него для "
               "тебя нет.")


def _fmt_day(view: DayView, bell, lunches, detail: str, is_teacher: bool,
             gcg) -> str:
    """Текст одного дня — тем же format_day, что и раньше.

    ``meta`` был перевёрнут: студент видел преподавателя, а преподаватель
    — группу. Плюс преподавателю нужно склеивать поток: физкультура у
    шести групп — это одна пара, а не шесть.
    """
    return format_day(
        view.date, view.lessons, bell, lunches, detail,
        meta="group" if is_teacher else "teacher",
        show_rov=not is_teacher,
        group_course_group=gcg,
        merge_groups=is_teacher,
    )


def render_day(view: DayView, *, bell, lunches, detail: str,
               is_teacher: bool, gcg=None) -> str:
    """Нарисовать экран дня.

    Параметры ``bell``/``lunches``/``detail``/``is_teacher``/``gcg``
    приходят от вызывающего: их знает пользователь и его настройки, а
    не состояние дня.
    """
    if view.identity_missing:
        return NO_IDENTITY

    if view.state == DayView.LESSONS:
        text = _fmt_day(view, bell, lunches, detail, is_teacher, gcg)
        if view.stale_when is not None:
            text += format_stale_warning(view.stale_when)
    elif view.state == DayView.CANCELLED:
        # Пары есть, но все отменены: рисуем зачёркнутые строки, а не
        # «Занятий нет» — студент должен видеть, что отменили.
        text = _fmt_day(view, bell, lunches, detail, is_teacher, gcg)
        if view.stale_when is not None:
            text += format_stale_warning(view.stale_when)
    elif view.state == DayView.NO_LESSONS:
        text = format_no_lessons(view.date)
        if view.stale_when is not None:
            text += format_stale_warning(view.stale_when)
    elif view.state == DayView.UNVERIFIED:
        text = format_unverified(view.date, view.stale_when)
    elif view.state == DayView.NOT_PUBLISHED:
        text = format_not_published(view.date)
        if view.stale_when is not None:
            text += format_stale_warning(view.stale_when)
    else:
        raise ValueError(f"неизвестное состояние дня: {view.state}")

    if view.nearest is not None:
        d, lessons = view.nearest
        # Подменяем дату и пары, чтобы переиспользовать тот же формат.
        near = DayView(date=d, state=DayView.LESSONS, lessons=lessons)
        text += "\n\nБлижайшее —\n" + _fmt_day(
            near, bell, lunches, detail, is_teacher, gcg)
    return text


def render_week(entries, *, bell, lunches, detail: str, is_teacher: bool,
                gcg=None) -> str:
    """Неделя: тот же format_day, склеенный по дням."""
    from common.schedule import format_week
    return format_week(
        entries, bell, lunches, detail,
        meta="group" if is_teacher else "teacher",
        show_rov=not is_teacher,
        group_course_group=gcg,
        merge_groups=is_teacher,
    )


# Что именно придёт при каждом режиме уведомлений. Показать пример дешевле,
# чем объяснять словами «звонок+конец пары» — человек не понимает разницу,
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


def render_settings(user) -> str:
    """Экран настроек с примером того, что придёт при текущем режиме."""
    mode = user.bell_mode if user.bell_mode in BELL_PREVIEW else BELL_OFF
    return (f"⚙️ <b>Настройки</b>\n\n"
            f"Уведомления: <b>{BELL_LABELS.get(mode, 'выкл')}</b>\n"
            f"{BELL_PREVIEW[mode]}\n\n"
            f"Выбери действие 👇")


def render_history_empty() -> str:
    """Прошедших дней нет — это норма, а не поломка."""
    return ("📜 <b>История расписания</b>\n\n"
            "Прошедших дней пока нет — они копятся по мере учёбы.")


def render_history_pick() -> str:
    return "📜 История расписания\n\nВыбери дату 👇"
