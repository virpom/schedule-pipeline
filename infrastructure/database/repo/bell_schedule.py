import datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from infrastructure.database.models import BellLunch, BellSchedule
from infrastructure.database.repo.base import BaseRepo


# day_type, course_group, para, start, h1_end, h2_start, end
DEFAULT_BELL = [
    ("MONDAY", "ALL", 0, "09:00", "09:20", "09:20", "09:20"),  # Разговоры о важном
    ("MONDAY", "I_IV", 1, "09:25", "10:10", "10:15", "11:00"),
    ("MONDAY", "I_IV", 2, "11:10", "11:55", "12:20", "13:05"),
    ("MONDAY", "I_IV", 3, "13:15", "14:00", "14:05", "14:50"),
    ("MONDAY", "I_IV", 4, "15:00", "15:45", "15:50", "16:35"),
    ("MONDAY", "I_IV", 5, "16:45", "17:30", "17:35", "18:20"),
    ("MONDAY", "I_IV", 6, "18:30", "19:15", "19:20", "20:05"),
    ("MONDAY", "II_III", 1, "09:25", "10:10", "10:15", "11:00"),
    ("MONDAY", "II_III", 2, "11:10", "11:55", "12:00", "12:45"),
    ("MONDAY", "II_III", 3, "13:15", "14:00", "14:05", "14:50"),
    ("MONDAY", "II_III", 4, "15:00", "15:45", "15:50", "16:35"),
    ("MONDAY", "II_III", 5, "16:45", "17:30", "17:35", "18:20"),
    ("MONDAY", "II_III", 6, "18:30", "19:15", "19:20", "20:05"),
    ("OTHER", "I_IV", 1, "09:00", "09:45", "09:50", "10:35"),
    ("OTHER", "I_IV", 2, "10:45", "11:30", "11:55", "12:40"),
    ("OTHER", "I_IV", 3, "12:50", "13:35", "13:40", "14:25"),
    ("OTHER", "I_IV", 4, "14:35", "15:20", "15:25", "16:10"),
    ("OTHER", "I_IV", 5, "16:20", "17:05", "17:10", "17:55"),
    # Шестая пара есть в «стандартное.docx» (18:05–18:50 / 18:55–19:40) и
    # в college_lesson (ДОУ-24, ПРф-24, ЭОф-24). Без строки format_day
    # подставлял заглушку «пара 6», и студент не знал времени.
    ("OTHER", "I_IV", 6, "18:05", "18:50", "18:55", "19:40"),
    ("OTHER", "II_III", 1, "09:00", "09:45", "09:50", "10:35"),
    ("OTHER", "II_III", 2, "10:45", "11:30", "11:35", "12:20"),
    ("OTHER", "II_III", 3, "12:50", "13:35", "13:40", "14:25"),
    ("OTHER", "II_III", 4, "14:35", "15:20", "15:25", "16:10"),
    ("OTHER", "II_III", 5, "16:20", "17:05", "17:10", "17:55"),
    ("OTHER", "II_III", 6, "18:05", "18:50", "18:55", "19:40"),
]

# day_type, course_group, lunch_start, lunch_end, para, position
DEFAULT_LUNCH = [
    ("OTHER", "I_IV", "11:30", "11:55", 2, "inside"),
    ("OTHER", "II_III", "12:20", "12:50", 2, "after"),
    ("MONDAY", "I_IV", "11:55", "12:20", 2, "inside"),
    ("MONDAY", "II_III", "12:45", "13:15", 2, "after"),
]


class BellScheduleRepo(BaseRepo):
    async def get_all(self) -> list[BellSchedule]:
        result = await self.session.execute(select(BellSchedule))
        return list(result.scalars().all())

    async def get_lunches(self) -> list[BellLunch]:
        result = await self.session.execute(select(BellLunch))
        return list(result.scalars().all())

    async def get_context(self):
        bell = {(b.day_type, b.course_group, b.para): b for b in await self.get_all()}
        lunches = {(l.day_type, l.course_group): l for l in await self.get_lunches()}
        return bell, lunches

    async def upsert(
            self,
            day_type: str,
            course_group: str,
            para: int,
            start: datetime.time,
            end: datetime.time,
            h1_end: datetime.time | None = None,
            h2_start: datetime.time | None = None,
    ) -> None:
        # Перерыв между академическими часами. Без него пара становится
        # сплошным блоком: экран теряет «09:00–09:45 / 09:50–10:35», а у
        # bell_mode=full пропадают напоминания о перемене. На проде
        # перерыв есть у 38 пар из 39 — структура реальная.
        h1 = h1_end or end
        h2 = h2_start or end
        await self.session.execute(
            insert(BellSchedule)
            .values(
                day_type=day_type,
                course_group=course_group,
                para=para,
                start=start,
                h1_end=h1,
                h2_start=h2,
                end=end,
            )
            .on_conflict_do_update(
                index_elements=["day_type", "course_group", "para"],
                set_=dict(start=start, h1_end=h1, h2_start=h2, end=end),
            )
        )
        await self.session.commit()

    async def seed_if_empty(self) -> None:
        """Завести недостающие звонки, не трогая существующие.

        Раньше метод молчал, если в таблице была хоть одна строка. Из-за
        этого правка DEFAULT_BELL не доходила до живой базы: на проде
        добавили 6-ю пару обычных дней и понедельника, а в bell_schedule
        осталось 42 строки без них, и студент продолжал видеть заглушку
        «пара 6».

        Теперь досыпаем то, чего нет. Существующие строки не меняем:
        их мог поправить админ через редактор, и затирать его правки
        нельзя.
        """
        existing = {(b.day_type, b.course_group, b.para)
                    for b in (await self.session.execute(
                        select(BellSchedule))).scalars()}
        rows = [
            {
                "day_type": d,
                "course_group": c,
                "para": p,
                "start": datetime.time.fromisoformat(s),
                "h1_end": datetime.time.fromisoformat(h1e),
                "h2_start": datetime.time.fromisoformat(h2s),
                "end": datetime.time.fromisoformat(e),
            }
            for d, c, p, s, h1e, h2s, e in DEFAULT_BELL
            if (d, c, p) not in existing
        ]
        if rows:
            await self.session.execute(insert(BellSchedule).values(rows))

        # Обеды — по тому же правилу: досыпаем недостающие, не дублируя.
        have_lunch = {(x.day_type, x.course_group, x.para, x.position)
                      for x in (await self.session.execute(
                          select(BellLunch))).scalars()}
        lunch_rows = [
            {
                "day_type": d,
                "course_group": c,
                "lunch_start": datetime.time.fromisoformat(s),
                "lunch_end": datetime.time.fromisoformat(e),
                "para": p,
                "position": pos,
            }
            for d, c, s, e, p, pos in DEFAULT_LUNCH
            if (d, c, p, pos) not in have_lunch
        ]
        if lunch_rows:
            await self.session.execute(insert(BellLunch).values(lunch_rows))
        await self.session.commit()
