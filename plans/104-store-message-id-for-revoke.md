# План 104: сохранять `message_id` — чтобы ошибочную рассылку можно было отозвать

**Приоритет:** средний. Сегодня ошибочную пачку удалить нельзя вообще —
только руками в клиенте Telegram, у каждого получателя отдельно.

**Трудоёмкость:** M (~60 строк + миграция).

## Проблема

`broadcaster.py:18` отправляет сообщение и **выбрасывает ответ**:

```python
async def send_message(bot, user_id, text, ...) -> bool:
    try:
        await bot.send_message(user_id, text, ...)   # <- ответ не сохранён
    ...
    else:
        return True
```

`bot.send_message` возвращает `types.Message` с полем `message_id`.
Он не нужен ни для чего, кроме удаления, — поэтому его и не сохраняли.

Итог: 26.10.2026 в 11:34 ушло **3220 сообщений** (14 дат × 230
подписчиков), и отозвать их было нечем. Проверил все восемь таблиц
прода на колонку с `message_id`:

```
users, chats, bell_reminder, day_snapshot,
schedule_edit, college_lesson, substitution, setting
```

Ни в одной нет. `deleteMessage` требует `chat_id` **и** `message_id`;
узнать id уже отправленного сообщения задним числом через Bot API
невозможно — метод `getUpdates` отдаёт только входящие.

## Ограничение Bot API, которое определяет решение

**Удалить можно только сообщение младше 48 часов.** Позже приходит
`BadRequest: message can't be deleted for everyone`.

Это значит: хранить `message_id` вечно бессмысленно. Таблица должна
чиститься, иначе она растёт без пользы — удалить старые записи всё
равно не выйдет.

## Что сделать

**Шаг 1 — таблица.**

```python
# infrastructure/database/models/sent_message.py
class SentMessage(Base, TableNameMixin):
    """Что бот отправил и когда — чтобы успеть отозвать.

    Bot API не даёт удалить сообщение старше 48 часов, поэтому записи
    старше двух суток чистит poller: держать их дальше не для чего.
    """
    __table_args__ = (
        UniqueConstraint("chat_id", "message_id", name="uc_sent_message"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    message_id: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16), default="")  # schedule | bell | edit
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, index=True)
```

**Шаг 2 — возвращать `message_id` из отправки.** Не менять сигнатуру
`send_message` (её зовут в семи местах и она возвращает `bool`) — добавить
отдельную функцию:

```python
async def send_tracked(bot, chat_id, text, kind, photo=None) -> types.Message | None:
    """Отправить и запомнить id — чтобы потом можно было отозвать."""
```

**Шаг 3 — запоминать в рассылке.** `broadcast_schedule` и
`broadcast_many` получают `repo` (или колбэк `on_sent`) и пишут строку
на каждую успешную отправку.

**Шаг 4 — кнопка «Отозвать последнюю рассылку»** в админке рядом с
существующей «🔔 Всем подписчикам» (`admin.py:542`):

```python
@admin_router.callback_query(lambda cb: cb.data == "adm:revoke")
async def cb_revoke(cb, repo, config):
    ...
```

Показывает: «Отправить 3220 сообщений за 26.10 11:34? Отозвать?» —
и по подтверждению удаляет пачкой, соблюдая лимит ~30 запросов/с.

**Шаг 5 — чистка.** В `poller_loop` рядом с `snapshot_past_days`
(раз в час) добавить `repo.sent_messages.purge_older(48)`. Одна строка
`DELETE FROM sent_message WHERE created_at < now - 48h`.

## Сколько места

```
230 получателей × 20 дат = 4600 строк на инцидент
строка: chat_id(8) + message_id(8) + kind + created_at(8) ≈ 45 байт
=> ~200 КБ на инцидент
```

С чисткой через 48 часов таблица стабильна на уровне 200–400 КБ.
Без чистки — те же 200 КБ на каждую рассылку, но удалять из неё всё
равно нечего.

## Проверено и признано корректным

**Лимит скорости уже соблюдается.** `broadcast_schedule` спит
`1/rate` между сообщениями (`broadcaster.py:75`). `notify_rate` берётся
из `settings["notify_rate"]`, а его дефолт в `setting.py:10` — **20**
сообщений в секунду, не 300. Для удаления нужен свой темп: Bot API даёт
~30 запросов/с, значит `asyncio.sleep(1/25)` и обработка
`TelegramRetryAfter` — она уже есть в `send_message`, но не в
`delete_message`.

**`TelegramForbiddenError` не мешает.** 15 получателей заблокировали
бота — у них `send_message` вернул `False`, `message_id` не появился,
удалять нечего. Строки для них просто не создадутся.

**Ошибка удаления не должна ломать цикл.** Если сообщение уже удалено
руками или старше 48 часов, придёт `BadRequest`. Ловить и продолжать —
как `send_message` ловит `TelegramBadRequest` (`broadcaster.py:24`).

**План 099 (заблокировавшие остаются `subscribed=1`) — соседний, не
дублирует.** Там про то, чтобы отписывать мёртвых; здесь про то, чтобы
иметь возможность отозвать живым.

## Риски

- **Миграция на живой базе.** Новая таблица, ничего не меняет в
  существующих. Безопасно.
- **Замедление рассылки.** Одна `INSERT` на сообщение при 20 msg/s —
  это 20 вставок/с в SQLite, ерунда. Но при инциденте 3220 сообщений
  это 3220 отдельных коммитов; на всякий случай лучше копить
  `[(chat_id, message_id)]` и вставлять пачкой раз в 50.
- **Права бота.** `deleteMessage` работает, если бот — автор сообщения
  (здесь так) или админ чата. В личке удаляет свои сообщения свободно.
- **48 часов — жёсткое ограничение.** Если инцидент заметили позже
  двух суток, отзыв не сработает. Тогда останется только просить людей
  удалить вручную — как сейчас.
