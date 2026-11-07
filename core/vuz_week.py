"""Учебные недели вуза: своя нумерация, не совпадающая с колледжем.

Живёт в ядре, потому что это правило предметной области, а не деталь
Telegram: от номера недели зависит, какие пары вообще попадают в день.
Раньше функция лежала в ``sync_vuz``, и ``schedule_layer`` тянул оттуда
импорт — то есть ядро зависело от сервиса синхронизации.

У вуза неделя считается от якоря: неделя якоря — первая. Якорь хранится
в настройках, потому что его сдвигают руками, если вуз переиграл сетку.
"""
from __future__ import annotations

import datetime
import logging

from infrastructure.database.repo.requests import RequestsRepo

log = logging.getLogger(__name__)

# Начало семестра 2026/2027. Значение по умолчанию, пока в настройках
# ничего не записано: без него чётность вуза считать не от чего.
DEFAULT_ANCHOR = datetime.date(2026, 8, 31)

ANCHOR_KEY = "vuz_week_anchor"


def vuz_week(date: datetime.date, anchor: datetime.date | None = None) -> int:
    """Номер учебной недели вуза для даты.

    Считается от якоря: неделя якоря — первая. У вуза своя нумерация,
    она не совпадает с чётностью колледжа.
    """
    anchor = anchor or DEFAULT_ANCHOR
    return (date - anchor).days // 7 + 1


async def get_anchor(repo: RequestsRepo) -> datetime.date:
    """Якорь учебной недели вуза из настроек."""
    raw = await repo.settings.get(ANCHOR_KEY)
    if raw:
        try:
            return datetime.date.fromisoformat(raw)
        except ValueError:
            log.warning("якорь недели вуза испорчен: %r", raw)
    return DEFAULT_ANCHOR


async def set_anchor(repo: RequestsRepo, value: datetime.date) -> None:
    await repo.settings.set(ANCHOR_KEY, value.isoformat())
