"""Редактор не предлагает группы вуза (план 143).

_ask_group собирал кнопки из обоих источников без фильтра. На проде
28.10: 130 групп, из них 93 @vuz (71%). Админ ошибался на первом же
неверном нажатии.

Правка вузовской группы не применяется: base_lesson для неё
перезапишется синком вуза при следующем опросе, а бот ответит «Убрано».
"""
import asyncio
from types import SimpleNamespace

from tgbot.handlers import admin


def _repo(groups):
    return SimpleNamespace(
        base_lessons=SimpleNamespace(get_groups=lambda: _await(groups)),
        college_lessons=SimpleNamespace(get_groups=lambda: _await([])),
    )


async def _await(value):
    return value


def _buttons(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row]


def _build(groups):
    captured = {}

    async def edit_text(text, reply_markup):
        captured["kb"] = reply_markup

    async def answer(text, reply_markup):
        captured["kb"] = reply_markup

    event = SimpleNamespace(message=SimpleNamespace(edit_text=edit_text),
                            answer=answer)
    state = SimpleNamespace(update_data=lambda **kw: _await(None))
    user = SimpleNamespace(id=1, group="ДП-26", teacher_name=None,
                           role="student", username=None, full_name="Тест")
    asyncio.run(admin._ask_group(event, _repo(groups), state, user))
    return captured["kb"]


def test_vuz_groups_excluded():
    kb = _build(["ДП-26", "СА - 26-2@vuz", "ИС-25"])
    datas = _buttons(kb)
    assert "adm:ed_grp:ДП-26" in datas
    assert "adm:ed_grp:ИС-25" in datas
    assert not any("@vuz" in d for d in datas), datas


def test_college_groups_kept():
    kb = _build(["ДП-26", "АТ-26", "ИП-26-2"])
    datas = [d for d in _buttons(kb) if d.startswith("adm:ed_grp:")]
    assert len(datas) == 3, datas


def test_only_vuz_leaves_no_groups():
    kb = _build(["СА - 26-2@vuz", "АП-24@vuz"])
    datas = [d for d in _buttons(kb) if d.startswith("adm:ed_grp:")]
    assert datas == [], datas
