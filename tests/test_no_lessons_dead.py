"""Заметки `no_lessons` больше не спрашиваются в хот-пути.

План 030. Таблицу заполнял старый парсер, разбирая «Занятий нет» из
ячеек файла расписания. После перехода на ЭИОС таких ячеек нет, и
`replace_date` не вызывается ниоткуда: четыре строки остались от
07–08.10.2026, новых не появляется.

При этом `get_note` вызывался на каждом показе пустого дня — три места
в двух модулях, по запросу в БД за данными, которых не будет никогда.

Таблицу и миграцию 0001 не трогаю: в ней история, и удаление снесло бы
пояснения к тем четырём датам. Убраны только читатели.
"""
import inspect

from tgbot.handlers import user
from tgbot.services import poller


def _code(module) -> str:
    """Исходник без комментариев."""
    src = inspect.getsource(module)
    return "\n".join(line.split("#", 1)[0] for line in src.splitlines())


def test_user_does_not_query_notes():
    assert "no_lessons.get_note" not in _code(user)


def test_poller_does_not_query_notes():
    assert "no_lessons.get_note" not in _code(poller)


def test_no_lessons_repo_removed():
    """Репозиторий убран целиком: он был единственным читателем."""
    from infrastructure.database.repo.requests import RequestsRepo

    assert not hasattr(RequestsRepo, "no_lessons")


def test_model_not_in_metadata():
    """Модель убрана из метаданных, но таблица в БД остаётся."""
    from infrastructure.database.models import Base

    assert "no_lessons" not in Base.metadata.tables


def test_migration_still_creates_table():
    """Историю не теряем: миграция 0001 по-прежнему создаёт таблицу.

    Если убрать её оттуда, на чистой базе таблицы не будет, и четыре
    старые заметки станут недоступны навсегда.
    """
    import glob

    src = open(glob.glob("migrations/versions/0001_baseline.py")[0]).read()
    assert '"no_lessons"' in src, "миграция перестала создавать таблицу"


def test_empty_day_still_renders():
    """Пустой день по-прежнему показывает «Занятий нет»."""
    from common.schedule import format_no_lessons
    import datetime

    text = format_no_lessons(datetime.date(2026, 11, 15))
    assert text.strip(), "пустое сообщение"
    assert "асписан" in text or "аняти" in text
