"""Интерактивная рассылка проверяет номер группы (план 061).

Админ нажимает «🎓 Группе», вводит «МУСОР», и бот отвечал «Введи текст
сообщения для группы МУСОР» — принимал опечатку за чистую монету.
Только после ввода текста, на подтверждении, он видел «отправить 0
пользователям», и весь ввод пропадал.

Командный путь /broadcast_group проверку имел с самого начала.
Интерактивный — нет.

Сначала план утверждал, что путь ведёт к находке 2 («пустой список
всем 227»). Проверил: находка 2 уже исправлена в cb_bc_send — None
значит «всем», пустой список значит «никому». Так что цена опечатки
сейчас — потерянный ввод, а не рассылка на всех. Проверка всё равно
нужна: админ узнаёт об опечатке сразу, а не через два экрана.
"""
import inspect
import types

import pytest

from tgbot.handlers import admin


def _src(fn) -> str:
    return inspect.getsource(fn)


def test_interactive_path_checks_group():
    assert "get_by_group" in _src(admin.m_group_broadcast)


def test_command_path_checks_group():
    assert "get_by_group" in _src(admin.broadcast_group_cmd)


def test_both_paths_same_check():
    """Один и тот же путь защиты, а не два разных."""
    for fn in (admin.m_group_broadcast, admin.broadcast_group_cmd):
        assert "if not users:" in _src(fn), fn.__name__


def test_group_unknown_stops():
    """Неизвестная группа — не переводим в состояние ввода текста."""
    src = _src(admin.m_group_broadcast)
    ret = src.index("return")
    set_state = src.index("set_state")
    assert ret < set_state, "состояние ставится до проверки группы"


def test_repo_in_signature():
    """Без repo проверять нечем — middleware инжектит его в каждый апдейт."""
    sig = inspect.signature(admin.m_group_broadcast)
    assert "repo" in sig.parameters


@pytest.mark.asyncio
async def test_unknown_group_tells_admin():
    """Прогон обработчика: на опечатку — понятный ответ и никакого состояния."""
    asked, states = [], []

    class _Users:
        async def get_by_group(self, g):
            return []

    class _Repo:
        users = _Users()

    class _State:
        async def update_data(self, **kw):
            states.append(("data", kw))

        async def set_state(self, s):
            states.append(("state", s))

    class _Msg:
        text = "мусор"

        async def answer(self, text, **kw):
            asked.append(text)

    await admin.m_group_broadcast(_Msg(), _Repo(), _State())
    assert asked, "админ не получил ответа"
    assert "МУСОР" in asked[0]
    assert states == [], "состояние изменилось при опечатке"


@pytest.mark.asyncio
async def test_known_group_proceeds():
    asked, states = [], []

    class _Users:
        async def get_by_group(self, g):
            return [types.SimpleNamespace(id=1)]

    class _Repo:
        users = _Users()

    class _State:
        async def update_data(self, **kw):
            states.append(("data", kw))

        async def set_state(self, s):
            states.append(("state", s))

    class _Msg:
        text = "дп-26"

        async def answer(self, text, **kw):
            asked.append(text)

    await admin.m_group_broadcast(_Msg(), _Repo(), _State())
    assert [s[0] for s in states] == ["data", "state"], states
    assert "ДП-26" in asked[0]


def test_empty_list_does_not_mean_everyone():
    """Находка 2 уже закрыта — держим это на месте."""
    src = _src(admin.cb_bc_send)
    assert "if ids is None:" in src
    assert "if not ids" not in src
