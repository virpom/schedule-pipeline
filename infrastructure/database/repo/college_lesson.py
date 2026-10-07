import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert

from common.schedule import teacher_base
from infrastructure.database.models import CollegeLesson
from infrastructure.database.repo.base import BaseRepo


class CollegeLessonRepo(BaseRepo):
    async def has_source(self, source_url: str) -> bool:
        result = await self.session.execute(
            select(CollegeLesson.id).where(CollegeLesson.source_url == source_url).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def bulk_upsert(self, lessons: list[dict]) -> None:
        if not lessons:
            return
        await self.session.execute(
            insert(CollegeLesson)
            .values(lessons)
            .on_conflict_do_nothing(index_elements=["date", "group", "para"])
        )
        await self.session.commit()

    async def replace_date(self, date: datetime.date, lessons: list[dict]) -> None:
        await self.session.execute(delete(CollegeLesson).where(CollegeLesson.date == date))
        await self.session.commit()
        await self.bulk_upsert(lessons)

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
        return sorted({teacher_base(t) for (t,) in result.all() if t})

    async def get_for_teacher_date(self, teacher_name: str, date: datetime.date) -> list[CollegeLesson]:
        return [l for l in await self.get_all_lessons()
                if l.date == date and teacher_base(l.teacher) == teacher_name]

    async def get_for_teacher_range(self, teacher_name: str, start: datetime.date, end: datetime.date) -> list[CollegeLesson]:
        return [l for l in await self.get_all_lessons()
                if start <= l.date <= end and teacher_base(l.teacher) == teacher_name]

    async def get_dates_for_teacher(self, teacher_name: str) -> list[datetime.date]:
        dates = {l.date for l in await self.get_all_lessons() if teacher_base(l.teacher) == teacher_name}
        return sorted(dates, reverse=True)

    async def get_all_for_teacher(self, teacher_name: str) -> list[CollegeLesson]:
        return [l for l in await self.get_all_lessons() if teacher_base(l.teacher) == teacher_name]
