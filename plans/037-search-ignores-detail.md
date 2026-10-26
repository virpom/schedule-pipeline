# План 037: поиск игнорирует выбранный режим, `/group` не проверяет группу

**Приоритет:** низкий. Оба — про недоделанную валидацию и
непоследовательность, а не про потерю данных.

**Трудоёмкость:** S (~15 строк).

## Часть 1: «Найти» игнорирует `bell_detail`

В `common/schedule.py:334`:

```python
def format_teacher_results(entries, bell, lunches, detail: str = DETAIL_BRIEF) -> str:
    parts = []
    for date, lessons in entries:
        parts.append(format_day(date, lessons, bell, lunches, detail, meta="group", show_rov=False))
    return "\n\n".join(parts)
```

Параметр `detail` есть, но **ни один вызывающий его не передаёт**:

```
user.py:947   format_teacher_results(entries, bell, lunches)      <- «Найти преподавателя»
user.py:978   format_teacher_results(entries, bell, lunches)      <- «Найти группу»
```

Оба получают `brief`, чем бы ни была настройка пользователя.

**Насколько это заметно.** На проде 52 человека из 227 переключили
режим:

```
brief  x175
lunch  x26
full   x26
```

Для них «Сегодня» показывает `09:00–09:45 / 09:50–10:35`, а «Найти
преподавателя» на той же паре — `09:00–10:35`. Один человек видит два
разных формата в двух экранах.

**Что сделать:**

```python
f"👨‍🏫 «{q}»:\n\n" + format_teacher_results(entries, bell, lunches, user.bell_detail)
f"👥 «{group}» — неделя:\n\n" + format_teacher_results(entries, bell, lunches, user.bell_detail)
```

Обе функции уже принимают `user` в аргументах — правка на два слова.

**Заметить:** `show_rov=False` в `format_teacher_results` — верно.
«Разговоры о важном» относятся к своей группе, а в чужом расписании
это шум.

## Часть 2: `/group` пишет что угодно

`tgbot/handlers/user.py:413`:

```python
@user_router.message(Command("group"))
async def set_group_cmd(message: Message, repo: RequestsRepo, user: User):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Формат: /group ТЭ-26ФП")
        return
    group = parts[1].strip().upper()
    await repo.users.set_group(user.id, group)
```

Ни одной проверки:

1. **Существует ли группа.** `/group ХХХ-99` запишется, `_day_text`
   вернёт `[]`, студент увидит «Занятий нет 🙌» и решит, что пар нет.
   Настоящая причина — опечатка в команде.
2. **Длина.** Колонка `group String(32)`, но SQLite **не проверяет
   длину VARCHAR** — ограничение живёт только в DDL. `/group` с сотней
   символов запишется молча.
3. **Формат.** Латиница, пробелы, эмодзи — всё пройдёт.

**Почему это хуже, чем кажется.** `/group` — единственный текстовый
ввод группы, и он же самый удобный. Инлайн-выбор (`cb_group`) берёт
имя из callback, то есть из списка, который бот сам построил, — там
ошибка невозможна. А `/group` пишет вслепую.

**Что сделать:**

```python
group = parts[1].strip().upper()
known = await repo.base_lessons.get_groups()
if group not in known:
    # Подсказать похожие — частая опечатка в одной букве.
    близкие = [g for g in known if group[:4] in g or g[:4] in group][:5]
    hint = "\n\nМожет быть: " + ", ".join(близкие) if близкие else ""
    await message.answer(
        f"Группы «{group}» нет в расписании.{hint}\n\n"
        f"Посмотреть список: /menu", reply_markup=BACK_KB)
    return
```

`get_groups()` возвращает все группы, включая `@vuz` — это правильно:
студент вуза тоже может ввести группу текстом.

## Проверено и признано корректным

**`course` в БД расходится с вычисленным по имени — но это не влияет
ни на что.** На проде 20 пар «группа + course» расходятся
(`ДП-26`: `course=None` у 8 человек, `=1` у 6). Причина в том, что
`course_from_group` считает от года поступления и текущей даты
(`26` → 2026 → 1 курс), а в БД лежит то, что человек выбрал руками
или что осталось с прошлого года.

Проверил все 5 мест, где используется `user.course`:

```
user.py:375   bells_group(user.group, user.course)   <- группа перекрывает
user.py:400   not user.course -> спросить курс         <- UX
user.py:427   if user.course -> показать меню          <- UX
user.py:591   if user.course -> показать меню          <- UX
bell.py:39    bells_group(user.group, user.course)     <- группа перекрывает
poller.py:172 bells_group(user.group, user.course)     <- группа перекрывает
```

`bells_group` устроен так:

```python
def bells_group(group, course=None):
    if group:
        return course_group_from_group(group)   # course игнорируется
    return course_group_from_course(course)
```

То есть **как только группа задана, `course` не используется вовсе**.
Расхождение — косметика в БД, а не баг отображения.

**`format_day` fallback по имени группы работает.** Когда
`group_course_group` не передан (как в `format_teacher_results`),
`course_group_from_group(grp)` вычисляет поток по имени. Проверил на
реальных: `ТЭ-26ФП` → `I_IV`, `ЮР-24А` → `II_III`, `ДП-23` → `I_IV`.
Совпадает с тем, что даёт `bells_group`.

**Звонки в БД корректны.** `09:00–10:35` — это честные 95 минут
с перерывом 5 минут (`h1_end=09:45`, `h2_start=09:50`), а не ошибка
склейки. В `detail=full` бот показывает оба академических часа
раздельно, в `brief` — общий интервал. Оба варианта верны.

## Риски

- **`/group` с проверкой сломает ввод группы вуза? Нет — проверено.**
  `vuz_group.name` хранит имена **с суффиксом** (`ГД-25оз@vuz`,
  `ЭК-24@vuz`), ровно как `base_lesson`. На проде:
  `base_lessons.get_groups()` = 129 групп (37 колледж + 92 `@vuz`),
  `vuz_group` = 92, все 92 совпадают. То есть `get_groups()` уже
  покрывает обе подсистемы, объединять с `vuz_groups` не нужно.
- **Подсказка «может быть» может угадать неверно.** Это только
  подсказка, запись не происходит — вреда нет.
- **`bell_detail` может содержать мусор.** `user.py:868` уже
  защищается: `if user.bell_detail in DETAIL_ORDER else DETAIL_ORDER[0]`.
  При прокидывании в поиск эта защита тоже сработает, потому что
  `format_day` сравнивает `detail == DETAIL_FULL` и иначе идёт в
  `_para_brief`.
