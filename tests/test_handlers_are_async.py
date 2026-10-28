"""Все обработчики aiogram — async и с первого аргумента-события.

28.10 на проде: `_subject_pick()` оформлен как обработчик `SubjectSearch.waiting`,
но это синхронная функция с сигнатурой `(lessons, subj)`. aiogram вызвал её
в пуле потоков с одним аргументом — `TypeError` на каждое сообщение
старосты в поиске по предмету, и текст не получал никто.

Ошибка невидима тестами: сами по себе и функция, и обработчик корректны,
неверна только связка. Проверяем связку целиком по зарегистрированным
наблюдателям, а не по коду.
"""
import asyncio
import inspect

from aiogram import Router

from tgbot.handlers import admin, editor, user


def _routers():
    return [user.user_router, admin.admin_router, editor.editor_router]


def _handlers(router: Router):
    return [h for h in router.message.handlers] + \
           [h for h in router.callback_query.handlers]


def test_all_handlers_are_coroutines():
    bad = []
    for router in _routers():
        for h in _handlers(router):
            fn = h.callback
            if not asyncio.iscoroutinefunction(fn):
                bad.append(f"{fn.__module__}.{fn.__qualname__}")
    assert not bad, "синхронные обработчики (aiogram уводит их в поток): " + ", ".join(bad)


def test_subject_search_decoration():
    """Именно тот случай: ищем обработчик поиска по предмету."""
    found = None
    for h in user.user_router.message.handlers:
        if h.callback.__name__ == "subject_answer":
            found = h.callback
    assert found is not None, "subject_answer больше не обработчик поиска"
    assert asyncio.iscoroutinefunction(found)
    params = list(inspect.signature(found).parameters)
    assert params[0] == "message", params


def test_subject_pick_is_plain_helper():
    """_subject_pick — утилита, а не обработчик."""
    assert not asyncio.iscoroutinefunction(user._subject_pick)
    names = [h.callback.__name__ for r in _routers() for h in _handlers(r)]
    assert "_subject_pick" not in names
