import datetime

from sqlalchemy import select, func
from sqlalchemy.dialects.sqlite import insert

from infrastructure.database.models import BellSchedule
from infrastructure.database.repo.base import BaseRepo


DEFAULT_BELL = [
    # day_type, course_group, para, start, end
    ("MONDAY", "ALL", 0, "09:00", "09:20"),  # Разговоры о важном
    ("MONDAY", "I_IV", 1, "09:25", "11:00"),
    ("MONDAY", "I_IV", 2, "11:10", "13:05"),
    ("MONDAY", "I_IV", 3, "13:15", "14:50"),
    ("MONDAY", "I_IV", 4, "15:00", "16:35"),
    ("MONDAY", "I_IV", 5, "16:45", "18:20"),
    ("MONDAY", "II_III", 1, "09:25", "11:00"),
    ("MONDAY", "II_III", 2, "11:10", "12:45"),
    ("MONDAY", "II_III", 3, "13:15", "14:50"),
    ("MONDAY", "II_III", 4, "15:00", "16:35"),
    ("MONDAY", "II_III", 5, "16:45", "18:20"),
    ("OTHER", "I_IV", 1, "09:00", "10:35"),
    ("OTHER", "I_IV", 2, "10:45", "12:40"),
    ("OTHER", "I_IV", 3, "12:50", "14:25"),
    ("OTHER", "I_IV", 4, "14:35", "16:10"),
    ("OTHER", "I_IV", 5, "16:20", "17:55"),
    ("OTHER", "II_III", 1, "09:00", "10:35"),
    ("OTHER", "II_III", 2, "10:45", "12:20"),
    ("OTHER", "II_III", 3, "12:50", "14:25"),
    ("OTHER", "II_III", 4, "14:35", "16:10"),
    ("OTHER", "II_III", 5, "16:20", "17:55"),
]


class BellScheduleRepo(BaseRepo):
    async def get_all(self) -> list[BellSchedule]:
        result = await self.session.execute(select(BellSchedule))
        return list(result.scalars().all())

    async def as_dict(self) -> dict[tuple[str, str, int], tuple[datetime.time, datetime.time]]:
        return {
            (b.day_type, b.course_group, b.para): (b.start, b.end)
            for b in await self.get_all()
        }

    async def upsert(
            self,
            day_type: str,
            course_group: str,
            para: int,
            start: datetime.time,
            end: datetime.time,
    ) -> None:
        await self.session.execute(
            insert(BellSchedule)
            .values(
                day_type=day_type,
                course_group=course_group,
                para=para,
                start=start,
                end=end,
            )
            .on_conflict_do_update(
                index_elements=["day_type", "course_group", "para"],
                set_=dict(start=start, end=end),
            )
        )
        await self.session.commit()

    async def seed_if_empty(self) -> None:
        result = await self.session.execute(select(func.count()).select_from(BellSchedule))
        if result.scalar_one() > 0:
            return
        rows = [
            {
                "day_type": d,
                "course_group": c,
                "para": p,
                "start": datetime.time.fromisoformat(s),
                "end": datetime.time.fromisoformat(e),
            }
            for d, c, p, s, e in DEFAULT_BELL
        ]
        await self.session.execute(insert(BellSchedule).values(rows))
        await self.session.commit()
