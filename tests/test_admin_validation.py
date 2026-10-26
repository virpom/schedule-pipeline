"""Админские команды проверяют ввод и пересобирают расписание.

План 026. Пять команд принимали ввод, который молча ломал расписание:

- `/setvuzanchor 1999-01-01` -> номер недели 1400 -> расписание вуза пусто
- `/setvuzanchor` не пересобирал `college_lesson` — студент видел старые
  данные до следующего прохода поллера (а если сайт лежит — всегда)
- `/setgroup ДП-2б` -> сохранялось `ДП-2Б` -> чат каждый день получал
  «пар нет»
- `/setgroup АП-23` для группы вуза (хранится как `АП-23@vuz`) создавал
  запись-призрак
- `/setpoll 999999999` -> `poller_loop` больше никогда не опрашивал сайт
"""
import datetime

import pytest

from tgbot.handlers import admin as admin_mod


class FakeMessage:
    def __init__(self, text="", chat_type="private", chat_id=1):
        self.text = text
        self.chat = type("Chat", (), {
            "id": chat_id, "type": chat_type, "title": "Тестовый чат"})()
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append(text)

    @property
    def last(self):
        return self.answers[-1] if self.answers else ""


class FakeSettings:
    def __init__(self):
        self.data = {}

    async def set(self, key, value):
        self.data[key] = value

    async def get(self, key):
        return self.data.get(key)

    async def get_all(self):
        return dict(self.data)


class FakeBaseLessons:
    def __init__(self, groups):
        self.groups = groups

    async def get_groups(self):
        return self.groups


class FakeChats:
    def __init__(self):
        self.saved = {}

    async def set_group(self, chat_id, title, group):
        self.saved[chat_id] = group


class FakeRepo:
    def __init__(self, groups=(), materialize_raises=None):
        self.settings = FakeSettings()
        self.base_lessons = FakeBaseLessons(list(groups))
        self.chats = FakeChats()
        self.materialize_calls = 0
        self._raises = materialize_raises


class FakeConfig:
    def __init__(self, admins=(1,)):
        self.tg_bot = type("T", (), {"admin_ids": list(admins)})()


def is_admin(msg, config):
    return msg.chat.id in config.tg_bot.admin_ids


@pytest.fixture
def admin(monkeypatch):
    """Подменяет _is_admin: у хендлеров он берётся из модуля."""
    monkeypatch.setattr(admin_mod, "_is_admin", is_admin)
    return admin_mod


# --- /setpoll -------------------------------------------------------------

@pytest.mark.asyncio
async def test_setpoll_rejects_huge_interval(admin):
    """Верхняя границы не было: /setpoll 999999999 замораживал опрос."""
    msg, repo = FakeMessage("/setpoll 999999999"), FakeRepo()
    await admin.set_poll(msg, repo, FakeConfig())
    assert "86400" in msg.last
    assert "poll_interval" not in repo.settings.data


@pytest.mark.asyncio
async def test_setpoll_accepts_valid(admin):
    msg, repo = FakeMessage("/setpoll 600"), FakeRepo()
    await admin.set_poll(msg, repo, FakeConfig())
    assert repo.settings.data["poll_interval"] == "600"


@pytest.mark.asyncio
async def test_setpoll_rejects_too_small(admin):
    msg, repo = FakeMessage("/setpoll 5"), FakeRepo()
    await admin.set_poll(msg, repo, FakeConfig())
    assert "poll_interval" not in repo.settings.data


# --- /setgroup ------------------------------------------------------------

@pytest.mark.asyncio
async def test_setgroup_rejects_unknown(admin):
    """Опечатка не должна создавать чат-призрак."""
    msg = FakeMessage("/setgroup НЕТ-ТАКОЙ", chat_type="group", chat_id=1)
    repo = FakeRepo(groups=["ДП-26", "ПРф-23"])
    await admin.set_chat_group(msg, repo, FakeConfig())
    assert "нет в расписании" in msg.last
    assert not repo.chats.saved


@pytest.mark.asyncio
async def test_setgroup_suggests_similar(admin):
    """При опечатке в последнем символе подсказываем похожие."""
    msg = FakeMessage("/setgroup ДП-2Б", chat_type="group", chat_id=1)
    repo = FakeRepo(groups=["ДП-26", "ДП-24", "ПРф-23"])
    await admin.set_chat_group(msg, repo, FakeConfig())
    assert "Похожие" in msg.last
    assert "ДП-26" in msg.last


@pytest.mark.asyncio
async def test_setgroup_adds_vuz_suffix(admin):
    """Группы вуза хранятся с @vuz — не заставляем админа его помнить."""
    msg = FakeMessage("/setgroup АП-23", chat_type="group", chat_id=1)
    repo = FakeRepo(groups=["АП-23@vuz", "ДП-26"])
    await admin.set_chat_group(msg, repo, FakeConfig())
    assert repo.chats.saved[1] == "АП-23@vuz"


@pytest.mark.asyncio
async def test_setgroup_accepts_known(admin):
    msg = FakeMessage("/setgroup дп-26", chat_type="group", chat_id=1)
    repo = FakeRepo(groups=["ДП-26"])
    await admin.set_chat_group(msg, repo, FakeConfig())
    assert repo.chats.saved[1] == "ДП-26"


# --- /setvuzanchor --------------------------------------------------------

@pytest.mark.asyncio
async def test_setvuzanchor_rejects_absurd_date(admin, monkeypatch):
    """1999-01-01 давал номер недели ~1400, и расписание вуза пустело."""
    from tgbot.services import sync_vuz

    called = []

    async def fake_set(repo, value):
        called.append(value)

    monkeypatch.setattr(sync_vuz, "set_anchor", fake_set)

    msg = FakeMessage("/setvuzanchor 1999-01-01")
    await admin.set_vuz_anchor(msg, FakeRepo(), FakeConfig())
    assert "учебного года" in msg.last
    assert not called, "якорь всё-таки записан"


@pytest.mark.asyncio
async def test_setvuzanchor_rebuilds(admin, monkeypatch):
    """Смена якоря должна сразу пересобрать college_lesson.

    Иначе студент видит старое расписание до следующего прохода поллера,
    а если сайт вуза лежит — до бесконечности.
    """
    from tgbot.services import sync_eios, sync_vuz

    rebuilt = []

    async def fake_set(repo, value):
        pass

    async def fake_materialize(repo):
        rebuilt.append(True)

    monkeypatch.setattr(sync_vuz, "set_anchor", fake_set)
    monkeypatch.setattr(sync_eios, "materialize", fake_materialize)

    today = datetime.date.today()
    msg = FakeMessage(f"/setvuzanchor {today - datetime.timedelta(days=30)}")
    await admin.set_vuz_anchor(msg, FakeRepo(), FakeConfig())
    assert rebuilt, "пересборки не было"
    assert "пересобрано" in msg.last.lower()


@pytest.mark.asyncio
async def test_setvuzanchor_survives_rebuild_failure(admin, monkeypatch):
    """Падение пересборки не должно молчать: админ должен узнать."""
    from tgbot.services import sync_eios, sync_vuz

    async def fake_set(repo, value):
        pass

    async def boom(repo):
        raise RuntimeError("диск кончился")

    monkeypatch.setattr(sync_vuz, "set_anchor", fake_set)
    monkeypatch.setattr(sync_eios, "materialize", boom)

    today = datetime.date.today()
    msg = FakeMessage(f"/setvuzanchor {today}")
    await admin.set_vuz_anchor(msg, FakeRepo(), FakeConfig())
    assert "не удалось" in msg.last.lower()
