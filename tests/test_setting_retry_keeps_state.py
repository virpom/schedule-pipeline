"""«Неверное значение. Попробуй ещё раз.» — и это должно работать (план 163).

`m_setting` обрабатывает ввод всех настроек. `state.clear()` стоял ДО
валидации: на «abc» бот отвечал «Попробуй ещё раз», но состояние уже
было пусто, и следующее верное «600» уходило мимо обработчика — в
catch-all any_text из user_router. Админ видел меню и терял настройку.

Проверяем именно связку «состояние + следующий ввод»: одна ошибка не
должна выбивать из диалога, а успешная запись — должна его закрывать.
"""
import pytest

from tgbot.handlers import admin


class FakeState:
    def __init__(self, state: str | None):
        self.state = state
        self.cleared = 0

    async def get_state(self):
        return self.state

    async def clear(self):
        self.cleared += 1
        self.state = None


class FakeSettings:
    def __init__(self):
        self.saved = {}

    async def set(self, key, val):
        self.saved[key] = val


class FakeRepo:
    def __init__(self):
        self.settings = FakeSettings()


class FakeMessage:
    def __init__(self, text):
        self.text = text
        self.answers = []

    async def answer(self, text, **kw):
        self.answers.append(text)


def _state():
    return admin.AdminState.set_poll.state


@pytest.mark.asyncio
async def test_bad_value_keeps_state():
    """Главный случай: состояния не трогаем, диалог продолжается."""
    state, repo = FakeState(_state()), FakeRepo()
    msg = FakeMessage("abc")

    await admin.m_setting(msg, repo, state)

    assert state.state == _state(), "состояние сброшено — «Попробуй ещё раз» врёт"
    assert state.cleared == 0
    assert "Попробуй ещё раз" in msg.answers[-1]
    assert repo.settings.saved == {}


@pytest.mark.asyncio
async def test_retry_after_error_saves_value():
    """Ровно то, что видел админ: ошибка, потом верное значение."""
    state, repo = FakeState(_state()), FakeRepo()

    await admin.m_setting(FakeMessage("abc"), repo, state)
    retry = FakeMessage("600")
    await admin.m_setting(retry, repo, state)

    assert repo.settings.saved == {"poll_interval": "600"}
    assert state.state is None, "после успешного сохранения из ввода не вышли"
    assert "600" in retry.answers[-1]


@pytest.mark.asyncio
async def test_valid_value_clears_state():
    """Успех закрывает диалог — иначе следующее сообщение снова в парсер."""
    state, repo = FakeState(_state()), FakeRepo()
    await admin.m_setting(FakeMessage("600"), repo, state)
    assert state.cleared == 1
    assert state.state is None


@pytest.mark.asyncio
async def test_unknown_state_clears_state():
    """Состояние есть, настройки с таким state нет (откат кода) — выходим."""
    state, repo = FakeState("AdminState:gone"), FakeRepo()
    msg = FakeMessage("600")

    await admin.m_setting(msg, repo, state)

    assert state.cleared == 1
    assert msg.answers == []
    assert repo.settings.saved == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("key, bad", [
    ("poll", "abc"), ("poll", "5"),
    ("rate", "abc"), ("rate", "99"),
    ("night", "23:00"), ("night", "25:00 07:00"),
    ("support", "не ссылка"),
])
async def test_every_setting_survives_bad_input(key, bad):
    """Дефект общий для всех настроек: все они идут через m_setting."""
    item = admin.SETTINGS[key]
    state, repo = FakeState(item.state.state), FakeRepo()

    await admin.m_setting(FakeMessage(bad), repo, state)

    assert state.state == item.state.state, (
        f"настройка {key} потеряла состояние на {bad!r}"
    )
    assert repo.settings.saved == {}
