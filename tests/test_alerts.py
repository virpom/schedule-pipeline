"""Тревоги админу: шлём один раз, пока проблема та же."""
import asyncio

from tgbot.services import alerts


class FakeSettings:
    def __init__(self):
        self.d = {}

    async def get(self, key):
        return self.d.get(key)

    async def set(self, key, value):
        self.d[key] = value


class FakeRepo:
    def __init__(self):
        self.settings = FakeSettings()


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


class FakeConfig:
    class tg_bot:
        admin_ids = [111]


def run(coro):
    return asyncio.run(coro)


def test_alert_sent_once_for_same_problem():
    """Одна и та же проблема не должна спамить каждый цикл опроса."""
    bot, repo, cfg = FakeBot(), FakeRepo(), FakeConfig()
    run(alerts.alert(bot, repo, cfg, "structure", "структура изменилась"))
    run(alerts.alert(bot, repo, cfg, "structure", "структура изменилась"))
    assert len(bot.sent) == 1


def test_alert_sent_again_when_problem_changes():
    """Другая ошибка — это другая новость."""
    bot, repo, cfg = FakeBot(), FakeRepo(), FakeConfig()
    run(alerts.alert(bot, repo, cfg, "structure", "ошибка А"))
    run(alerts.alert(bot, repo, cfg, "structure", "ошибка Б"))
    assert len(bot.sent) == 2


def test_different_kinds_do_not_shadow_each_other():
    bot, repo, cfg = FakeBot(), FakeRepo(), FakeConfig()
    run(alerts.alert(bot, repo, cfg, "structure", "одно"))
    run(alerts.alert(bot, repo, cfg, "site", "другое"))
    assert len(bot.sent) == 2


def test_clear_silent_when_no_alert_was_sent():
    """Нечего закрывать — не пишем «восстановилось» на пустом месте."""
    bot, repo, cfg = FakeBot(), FakeRepo(), FakeConfig()
    run(alerts.clear(bot, repo, cfg, "structure", "всё ок"))
    assert bot.sent == []


def test_clear_reports_recovery_once():
    bot, repo, cfg = FakeBot(), FakeRepo(), FakeConfig()
    run(alerts.alert(bot, repo, cfg, "structure", "сломалось"))
    run(alerts.clear(bot, repo, cfg, "structure", "починилось"))
    run(alerts.clear(bot, repo, cfg, "structure", "починилось"))
    assert len(bot.sent) == 2
    assert "Восстановилось" in bot.sent[1][1]


def test_alert_goes_to_every_admin():
    bot, repo = FakeBot(), FakeRepo()

    class TwoAdmins:
        class tg_bot:
            admin_ids = [111, 222]

    run(alerts.alert(bot, repo, TwoAdmins(), "structure", "проблема"))
    assert [uid for uid, _ in bot.sent] == [111, 222]


def test_long_text_does_not_overflow_setting():
    """В setting.value всего 128 символов — храним хеш, а не текст."""
    bot, repo, cfg = FakeBot(), FakeRepo(), FakeConfig()
    long_text = "очень длинная ошибка " * 50
    run(alerts.alert(bot, repo, cfg, "structure", long_text))
    stored = repo.settings.d["alert_structure"]
    assert len(stored) == 64  # sha256 hex
