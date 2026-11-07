"""Оставлено для совместимости: код переехал в ``core.source_state``.

Состояние источника — это про базу и время, а не про мессенджер,
поэтому живёт в ядре. Импорт отсюда работает как раньше.
"""
from core.source_state import (_night_length, in_night, is_stale,  # noqa: F401
                               is_stale_vuz, last_ok, last_ok_vuz, mark_ok,
                               mark_ok_vuz, stale_after)
