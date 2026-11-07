"""Оставлено для совместимости: код переехал в ``core.schedule_layer``.

Ядро — это всё, что не зависит от Telegram. Сборка расписания из слоёв
такова: она знает про базу и про часы, но не про мессенджер.
Импорт отсюда работает как раньше, новый код должен брать из ``core``.
"""
from core.schedule_layer import (PARITY_OFFSET, Slot, _collapse_same_para,  # noqa: F401
                                 _join_paired, get_day_slots, week_parity)
