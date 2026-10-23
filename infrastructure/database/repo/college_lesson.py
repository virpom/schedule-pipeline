import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert

from common.schedule import teacher_base, teacher_matches
from infrastructure.database.models import CollegeLesson
from infrastructure.database.repo.base import BaseRepo


class CollegeLessonRepo(BaseRepo):
    async def bulk_insert(self, lessons: list[dict]) -> None:
        """Вставить пары как есть.

        Без ``ON CONFLICT``: у ``college_lesson`` нет уникального индекса
        (см. модель), а согласованность держит ``replace_date()`` — он
        сначала удаляет все пары за дату.
        """
        if not lessons:
            return
        await self.session.execute(insert(CollegeLesson).values(lessons))
        await self.session.commit()

    async def bulk_upsert(self, lessons: list[dict]) -> None:
        """Устаревшее имя, оставлено для совместимости."""
        await self.bulk_insert(lessons)

    async def replace_date(self, date: datetime.date, lessons: list[dict]) -> None:
        await self.session.execute(delete(CollegeLesson).where(CollegeLesson.date == date))
        await self.session.commit()
        await self.bulk_insert(lessons)

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

    async def count_dates(self) -> int:
        result = await self.session.execute(select(func.count(func.distinct(CollegeLesson.date))))
        return result.scalar_one()

    async def get_latest_date(self) -> datetime.date | None:
        result = await self.session.execute(select(func.max(CollegeLesson.date)))
        return result.scalar_one()

    async def get_teachers(self) -> list[str]:
        result = await self.session.execute(select(CollegeLesson.teacher).distinct())
        names = {teacher_base(t) for (t,) in result.all() if t}
        surnames_with_initials = {n.split()[0] for n in names if len(n.split()) > 1}
        return sorted(
            n for n in names
            if len(n.split()) > 1 or n.split()[0] not in surnames_with_initials
        )

    # --- Выборка по преподавателю -----------------------------------------
    #
    # В БД преподаватель хранится по-разному: «Ляшко Д.В.», «Ляшко»,
    # «Ляшко Д.В., 1-ая подгруппа». Поэтому фильтруем по SQL (дата + фамилия),
    # а точное совпадение проверяем в Python через teacher_matches.
    # Раньше здесь грузилась вся таблица — на каждый тик bell-лупа.

    async def get_for_teacher_date(self, teacher_name: str, date: datetime.date) -> list[CollegeLesson]:
        surname = teacher_name.split()[0] if teacher_name.split() else teacher_name
        result = await self.session.execute(
            select(CollegeLesson)
            .where(CollegeLesson.date == date,
                   CollegeLesson.teacher.like(f"%{surname}%"))
            .order_by(CollegeLesson.para)
        )
        return [l for l in result.scalars().all() if teacher_matches(l.teacher, teacher_name)]

    async def get_for_teacher_range(self, teacher_name: str, start: datetime.date,
                                    end: datetime.date) -> list[CollegeLesson]:
        surname = teacher_name.split()[0] if teacher_name.split() else teacher_name
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
