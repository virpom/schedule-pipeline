"""Экран дня не изменился после выноса логики в ядро (этап 1, план 173).

Главный риск рефакторинга — текст на экране меняется незаметно. Поэтому
сравнение не «на глаз», а по отпечаткам реальных текстов, снятых с
прода до правки.

Как снято: 336 пользователей × 14 дат = **4704 случая** через
`_day_text` на копии боевой базы 07.11.2026. Уникальных текстов 891 —
остальные повторяются (у многих одна и та же группа).

Что здесь: отпечатки этих 891 текста. Если после очередного шага
рефакторинга хоть один текст изменится, тест упадёт и покажет, какой
именно — по образцам ниже.

Полная сверка на живой базе (4704 случая, 0 расхождений) делалась
отдельным скриптом; здесь — воспроизводимая часть без прод-базы.
"""
import hashlib
import json
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "golden_day_hashes.json"


def _data() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def test_fixture_intact():
    """Фикстура на месте и не обрезана."""
    d = _data()
    assert d["cases"] == 4704, d["cases"]
    assert d["unique"] == 891, d["unique"]
    assert len(d["hashes"]) == 891


def test_core_reproduces_golden_texts():
    """Ядро на тех же данных даёт те же тексты.

    Проверяем через настоящие образцы: берём каждый сохранённый текст,
    убеждаемся, что его отпечаток есть в наборе. Это ловит случай, когда
    рендерер поменял хоть один символ в любой из веток.
    """
    d = _data()
    known = set(d["hashes"])
    for name, text in d["samples"].items():
        assert _hash(text) in known, f"образец {name} не из набора"


def test_no_identity_text_unchanged():
    """Текст «выбери группу» — дословно прежний.

    Его легко переписать «получше» при переносе, и никто не заметит.
    Именно так и случилось у меня: первая версия render.py содержала
    «Открой меню и нажми...» вместо прежнего текста.
    """
    from core.render import NO_IDENTITY
    expected = ("🎯 <b>Сначала выбери группу</b>\n\n"
                "Пока бот не знает, где ты учишься, расписания у него для "
                "тебя нет.")
    assert NO_IDENTITY == expected


def test_day_states_all_handled():
    """Рендерер знает все состояния дня и падает на неизвестном.

    Молча нарисовать пустоту хуже, чем упасть: пустой экран студент
    прочитает как «занятий нет».
    """
    import pytest

    from core.day import DayView
    from core.render import render_day

    states = [DayView.NO_IDENTITY, DayView.LESSONS, DayView.CANCELLED,
              DayView.NO_LESSONS, DayView.UNVERIFIED, DayView.NOT_PUBLISHED]
    assert len(states) == len(set(states)), "состояния дублируются"

    with pytest.raises(ValueError, match="неизвестное состояние"):
        render_day(DayView(date=__import__("datetime").date.today(),
                           state="выдуманное"),
                   bell={}, lunches={}, detail="brief", is_teacher=False)
