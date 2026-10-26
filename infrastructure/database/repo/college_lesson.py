import datetime
import hashlib

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert

from common.schedule import VUZ_SUFFIX, teacher_base, teacher_matches
from infrastructure.database.models import BaseLesson, CollegeLesson
from infrastructure.database.repo.base import BaseRepo


def _clean_teacher_names(raw) -> list[str]:
    """Убрать дубли и мусор из списка преподавателей.

    Один человек бывает записан по-разному («Кокошка И.П.» и «Кокошка
    И. П.»). После нормализации остаётся одна запись. Фамилия без
    инициалов отбрасывается, если есть полный вариант: иначе в списке
    висят «Ляшко» и «Ляшко Д.В.» как два разных человека.
    """
    names = {teacher_base(t) for t in raw if t and teacher_base(t)}
    surnames_with_initials = {n.split()[0] for n in names if len(n.split()) > 1}
    return sorted(
        n for n in names
        if len(n.split()) > 1 or n.split()[0] not in surnames_with_initials
    )


class CollegeLessonRepo(BaseRepo):
    async def bulk_insert(self, lessons: list[dict]) -> None:
        """Вставить пары как есть, одним коммитом.

        Без ``ON CONFLICT``: согласованность держит ``replace_date()`` —
        он сначала удаляет все пары за дату. Уникальный индекс
        ``uc_college_lesson`` при этом работает как страховка: наложение
        двух пар вуза упадёт, а не создаст дубль.
        """
        if not lessons:
            return
        await self.session.execute(insert(CollegeLesson).values(lessons))
        await self.session.commit()

    async def replace_date(self, date: datetime.date, lessons: list[dict]) -> None:
        """Заменить все пары за дату одной транзакцией.

        Раньше здесь было два коммита: delete фиксировался отдельно, и
        упавшая вставка оставляла день пустым. ``materialize`` зовёт
        этот метод 14 раз подряд, так что падение на восьмом дне давало
        ровно один пустой день посреди окна — студент видел «Занятий
        нет» за конкретное число, остальные дни были в порядке.

        Откат обязателен: после ошибки сессия остаётся в состоянии
        «транзакция сломана», и без rollback delete применится, а insert
        нет — день всё равно опустеет.
        """
        try:
            await self.session.execute(
                delete(CollegeLesson).where(CollegeLesson.date == date))
            if lessons:
                await self.session.execute(insert(CollegeLesson).values(lessons))
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    async def get_for_group_date(
            self, group: str, date: datetime.date
    ) -> list[CollegeLesson]:
        result = await self.session.execute(
            select(CollegeLesson)
            .where(CollegeLesson.group == group, CollegeLesson.date == date)
            .order_by(CollegeLesson.para)
        )
        return list(result.scalars().all())

    async def get_for_group_range(
            self, group: str, start: datetime.date, end: datetime.date
    ) -> list[CollegeLesson]:
        result = await self.session.execute(
            select(CollegeLesson)
            .where(CollegeLesson.group == group, CollegeLesson.date >= start, CollegeLesson.date <= end)
            .order_by(CollegeLesson.date, CollegeLesson.para)
        )
        return list(result.scalars().all())

    async def get_groups(self) -> list[str]:
        result = await self.session.execute(
            select(CollegeLesson.group).distinct().order_by(CollegeLesson.group)
        )
        return list(result.scalars().all())

    async def get_dates_for_group(self, group: str) -> list[datetime.date]:
        result = await self.session.execute(
            select(CollegeLesson.date)
            .where(CollegeLesson.group == group)
            .distinct()
            .order_by(CollegeLesson.date.desc())
        )
        return list(result.scalars().all())

    async def get_all_for_group(self, group: str) -> list[CollegeLesson]:
        result = await self.session.execute(
            select(CollegeLesson)
            .where(CollegeLesson.group == group)
            .order_by(CollegeLesson.date.desc(), CollegeLesson.para)
        )
        return list(result.scalars().all())

    async def get_all_lessons(self) -> list[CollegeLesson]:
        result = await self.session.execute(
            select(CollegeLesson).order_by(CollegeLesson.date, CollegeLesson.para)
        )
        return list(result.scalars().all())

    async def count_lessons(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(CollegeLesson))
        return result.scalar_one()

    async def digest_by_date(self) -> dict[datetime.date, dict[str, str]]:
        """Отпечаток содержимого каждой группы на каждую дату.

        Нужен рассылке. Файл на сайте перезаписывается целиком, поэтому
        флаг «очное расписание изменилось» срабатывает от одной строки —
        а уведомление уходило на все даты замен сразу. Человек получал
        полтора десятка сообщений «расписание изменилось», хотя менялось
        одно.

        Отпечаток считается по группе, а не по дате целиком: иначе одна
        исправленная строка у ``ДП-26`` тянула бы рассылку всем 230
        подписчикам, включая тех, у кого в этот день ничего не менялось.
        """
        result = await self.session.execute(
            select(CollegeLesson).order_by(
                CollegeLesson.date, CollegeLesson.group, CollegeLesson.para)
        )
        buckets: dict[tuple[datetime.date, str], list] = {}
        for row in result.scalars().all():
            buckets.setdefault((row.date, row.group), []).append(
                (row.para, row.subject, row.teacher, row.room,
                 row.changed, row.action))
        digests: dict[datetime.date, dict[str, str]] = {}
        for (date, group), rows in buckets.items():
            digests.setdefault(date, {})[group] = hashlib.sha256(
                repr(rows).encode()).hexdigest()
        return digests

    async def count_dates(self) -> int:
        result = await self.session.execute(select(func.count(func.distinct(CollegeLesson.date))))
        return result.scalar_one()

    async def get_latest_date(self) -> datetime.date | None:
        result = await self.session.execute(select(func.max(CollegeLesson.date)))
        return result.scalar_one()

    async def get_teachers(self, vuz: bool | None = None) -> list[str]:
        """Преподаватели из расписания, по одному на человека.

        ``vuz``: True — только вуз, False — только колледж, None — все.
        Раньше выборки не было вовсе, и в списке «выбери себя» лежали
        235 имён колледжа без единого преподавателя вуза.
        """
        query = select(CollegeLesson.teacher).distinct()
        if vuz is True:
            query = query.where(CollegeLesson.group.like(f"%{VUZ_SUFFIX}"))
        elif vuz is False:
            query = query.where(CollegeLesson.group.notlike(f"%{VUZ_SUFFIX}"))
        result = await self.session.execute(query)
        return _clean_teacher_names(t for (t,) in result.all() if t)

    async def get_teachers_vuz(self) -> list[str]:
        """Преподаватели вуза: их пары лежат в base_lesson, не в college_lesson."""
        result = await self.session.execute(
            select(BaseLesson.teacher)
            .where(BaseLesson.group.like(f"%{VUZ_SUFFIX}"))
            .distinct()
        )
        return _clean_teacher_names(t for (t,) in result.all() if t)

    # --- Выборка по преподавателю -----------------------------------------
    #
    # В БД преподаватель хранится по-разному: «Ляшко Д.В.», «Ляшко»,
    # «Ляшко Д.В., 1-ая подгруппа». Поэтому фильтруем по SQL (дата + фамилия),
    # а точное совпадение проверяем в Python через teacher_matches.
    # Раньше здесь грузилась вся таблица — на каждый тик bell-лупа.

    async def get_for_teacher_date(self, teacher_name: str, date: datetime.date) -> list[CollegeLesson]:
        # Пустое имя — не «все преподаватели», а «преподаватель не выбран».
        # Без этой проверки фильтр превращался в LIKE '%%' и человек
        # видел пары всего колледжа и вуза разом.
        if not (teacher_name or "").strip():
            return []
        surname = teacher_name.split()[0]
        result = await self.session.execute(
            select(CollegeLesson)
            .where(CollegeLesson.date == date,
                   CollegeLesson.teacher.like(f"%{surname}%"))
            .order_by(CollegeLesson.para)
        )
        return [l for l in result.scalars().all() if teacher_matches(l.teacher, teacher_name)]

    async def get_for_teacher_range(self, teacher_name: str, start: datetime.date,
                                    end: datetime.date) -> list[CollegeLesson]:
        if not (teacher_name or "").strip():
            return []
        surname = teacher_name.split()[0]
        result = await self.session.execute(
            select(CollegeLesson)
            .where(CollegeLesson.date >= start, CollegeLesson.date <= end,
                   CollegeLesson.teacher.like(f"%{surname}%"))
            .order_by(CollegeLesson.date, CollegeLesson.para)
        )
        return [l for l in result.scalars().all() if teacher_matches(l.teacher, teacher_name)]

    async def get_dates_for_teacher(self, teacher_name: str) -> list[datetime.date]:
        surname = teacher_name.split()[0] if teacher_name.split() else teacher_name
        result = await self.session.execute(
            select(CollegeLesson.date, CollegeLesson.teacher)
            .where(CollegeLesson.teacher.like(f"%{surname}%"))
            .distinct()
        )
        dates = {d for d, t in result.all() if teacher_matches(t, teacher_name)}
        return sorted(dates, reverse=True)

    async def get_all_for_teacher(self, teacher_name: str) -> list[CollegeLesson]:
        surname = teacher_name.split()[0] if teacher_name.split() else teacher_name
        result = await self.session.execute(
            select(CollegeLesson)
            .where(CollegeLesson.teacher.like(f"%{surname}%"))
            .order_by(CollegeLesson.date, CollegeLesson.para)
        )
        return [l for l in result.scalars().all() if teacher_matches(l.teacher, teacher_name)]
