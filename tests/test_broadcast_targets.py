"""Рассылка пустой группе не должна превращаться в «всем».

План 002. `broadcast_ids = []` — falsy, поэтому срабатывала ветка
`else`, и рассылка уходила **всем 227 пользователям**, хотя
подтверждение показывало «Отправить 0 пользователям». Отозвать
сообщение в Telegram нельзя.

Достижимо в любой момент: на проде 8 из 37 групп не имеют ни одного
пользователя.
"""
import inspect
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base, User
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.handlers import admin


async def make_env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def user(uid, group):
    return User(id=uid, full_name=f"Пользователь {uid}", role="student",
                group=group, subscribed=True, bell_detail="brief",
                bell_mode="off", send_image=False)


async def test_empty_group_returns_empty_not_all():
    """`get_subscribed_by_group` на пустой группе даёт [], а не всех.

    Это вход в баг: `_target_users` возвращает пустой список, и именно
    он раньше считался «списка нет».
    """
    engine, pool = await make_env()
    try:
        async with pool() as db:
            repo = RequestsRepo(db)
            db.add_all([user(1, "ДП-26"), user(2, "ЭК-25")])
            await db.commit()

            users, label = await admin._target_users(repo, "ПУСТАЯ-ГРУППА")
            assert users == []
            assert "ПУСТАЯ-ГРУППА" in label
    finally:
        await engine.dispose()


async def test_broadcast_ids_none_means_all():
    """None — «списка нет», по-прежнему все подписчики.

    Разделение None и [] — суть правки.
    """
    src = inspect.getsource(admin.cb_bc_send)
    assert "if ids is None:" in src, (
        "нет разделения None и [] — план 002"
    )
    # Старая форма `if ids else` ловила и пустой список.
    assert "if ids else" not in src


async def test_confirm_refuses_zero_recipients():
    """Кнопку «Отправить» не показывают, когда получателей ноль."""
    src = inspect.getsource(admin._confirm_broadcast)
    assert "if not users:" in src
    # Сообщение должно объяснять, а не просто молчать.
    assert "никого нет" in src
    # И состояние не должно остаться висеть.
    assert "state.clear()" in src


async def test_confirm_with_zero_users_does_not_set_state():
    """Проверяем поведение, а не текст: при нуле state не заполняется."""
    engine, pool = await make_env()
    try:
        async with pool() as db:
            repo = RequestsRepo(db)
            state = AsyncMock()
            message = AsyncMock()

            await admin._confirm_broadcast(message, repo, state, "текст",
                                           users=[], label="в группе X")

            state.update_data.assert_not_awaited()
            state.set_state.assert_not_awaited()
            message.answer.assert_awaited()
            said = message.answer.await_args.args[0]
            assert "никого нет" in said
    finally:
        await engine.dispose()


async def test_confirm_with_users_sets_state():
    """Непустая аудитория работает как раньше."""
    engine, pool = await make_env()
    try:
        async with pool() as db:
            repo = RequestsRepo(db)
            state = AsyncMock()
            message = AsyncMock()

            await admin._confirm_broadcast(message, repo, state, "текст",
                                           users=[user(1, "ДП-26")],
                                           label="пользователям")

            state.update_data.assert_awaited()
            state.set_state.assert_awaited()
    finally:
        await engine.dispose()
