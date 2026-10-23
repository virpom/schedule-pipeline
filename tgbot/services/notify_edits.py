"""Уведомления об изменениях расписания и архив прошедших дней.

Когда староста правит расписание, об этом узнают только подписчики
его группы (не все 215 человек). Тексты уходят вне очереди, но с
соблюдением скорости рассылки.
"""
import datetime
import logging

from aiogram import Bot

from common.schedule import WEEKDAY_FULL
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.services.broadcaster import broadcast_many
from tgbot.services.schedule_layer import Slot, get_day_slots


def _fmt_day(date: datetime.date) -> str:
    return f"{WEEKDAY_FULL[date.weekday()]}, {date.day}.{date.month:02d}"


async def notify_group_about_edit(
        bot: Bot, repo: RequestsRepo, group: str, date: datetime.date | None,
        author_id: int | None, rate: float = 20.0) -> int:
    """Разослать подписчикам группы текст «расписание изменилось»."""
    subscribers = await repo.users.get_subscribed_by_group(group)
    targets = [u.id for u in subscribers if u.id != author_id]
    if not targets:
        return 0

    if date is None:
        header = "✏️ <b>Изменено базовое расписание</b>"
        body = f"Группа <b>{group}</b>"
    else:
        header = "🔄 <b>Изменение в расписании</b>"
        slots = await get_day_slots(repo, group, date)
        body = f"📅 <b>{_fmt_day(date)}</b> · группа <b>{group}</b>\n"
        body += _slots_text(slots)

    text = f"{header}\n\n{body}\n\n<i>Проверь расписание командой /start</i>"
    items = [(uid, text) for uid in targets]
    sent = await broadcast_many(bot, items, rate=rate)
    logging.info("notify_group_about_edit: %s на %s → %d/%d",
                 group, date, sent, len(targets))
    return sent


def _slots_text(slots: list[Slot]) -> str:
    if not slots:
        return "Занятий нет 🙌"
    lines = []
    for s in slots:
        flag = " 🔄" if s.changed else ""
        lines.append(f"<b>{s.para})</b> {s.subject}{flag}")
        meta = " · ".join(x for x in (s.teacher, s.room) if x)
        if meta:
            lines.append(f"     {meta}")
    return "\n".join(lines)


async def snapshot_past_days(repo: RequestsRepo, days_back: int = 3) -> int:
    """Сохранить в архив расписание прошедших дней.

    Учебный день кончился — фиксируем, что было (база + замены на тот
    момент). Раньше этого не делалось: если сайт обновит файл задним
    числом, история потерялась бы.
    """
    today = datetime.date.today()
    saved = 0
    for delta in range(1, days_back + 1):
        date = today - datetime.timedelta(days=delta)
        if date.isoweekday() == 7:      # воскресенье — не учебный день
            continue
        groups = await repo.base_lessons.get_groups()
        for group in groups:
            if await repo.snapshots.exists(date, group):
                continue
            slots = await get_day_slots(repo, group, date)
            if not slots:
                continue
            await repo.snapshots.save(date, group, slots)
            saved += 1
    if saved:
        logging.info("snapshot_past_days: сохранено %d дней", saved)
    return saved
