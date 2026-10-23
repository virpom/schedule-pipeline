import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert

from common.schedule import PARITY_ANY
from infrastructure.database.models import BaseLesson
from infrastructure.database.repo.base import BaseRepo


class BaseLessonRepo(BaseRepo):
    async def get_day(self, group: str, weekday: int, parity: str) -> list[BaseLesson]:
        """Пары группы на день недели с учётом чётности.

        Берём строки нужной чётности и ANY (одинаковые каждую неделю);
        при совпадении слота приоритет у конкретной чётности.
        """
        result = await self.session.execute(
            select(BaseLesson)
            .where(
                BaseLesson.group == group,
                BaseLesson.weekday == weekday,
                BaseLesson.week_parity.in_([parity, PARITY_ANY]),
            )
            .order_by(BaseLesson.para)
        )
        specific, any_rows = {}, {}
        for l in result.scalars().all():
            if l.week_parity == PARITY_ANY:
                any_rows[l.para] = l
            else:
                specific[l.para] = l
        merged = {**any_rows, **specific}
        return [merged[p] for p in sorted(merged)]

    async def get_week(self, group: str, parity: str) -> list[BaseLesson]:
        result = await self.session.execute(
            select(BaseLesson)
            .where(BaseLesson.group == group,
                   BaseLesson.week_parity.in_([parity, PARITY_ANY]))
            .order_by(BaseLesson.weekday, BaseLesson.para)
        )
        return list(result.scalars().all())

    async def upsert(self, group: str, parity: str, weekday: int, para: int,
                     subject: str, teacher: str = "", room: str = "",
                     source: str = "manual", updated_by: int | None = None) -> None:
        now = datetime.datetime.now()
        await self.session.execute(
            insert(BaseLesson)
            .values(group=group, week_parity=parity, weekday=weekday, para=para,
                    subject=subject, teacher=teacher, room=room,
                    source=source, updated_by=updated_by, updated_at=now)
            .on_conflict_do_update(
                index_elements=["group", "week_parity", "weekday", "para"],
                set_=dict(subject=subject, teacher=teacher, room=room,
                          source=source, updated_by=updated_by, updated_at=now),
            )
        )
        await self.session.commit()

    async def delete_slot(self, group: str, parity: str, weekday: int, para: int) -> None:
        await self.session.execute(
            delete(BaseLesson).where(
                BaseLesson.group == group,
                BaseLesson.week_parity == parity,
                BaseLesson.weekday == weekday,
                BaseLesson.para == para,
            )
        )
        await self.session.commit()

    async def count(self) -> int:
        from sqlalchemy import func
        result = await self.session.execute(select(func.count()).select_from(BaseLesson))
        return result.scalar_one()

    async def get_groups(self) -> list[str]:
        """Группы, у которых есть базовое расписание."""
        result = await self.session.execute(
            select(BaseLesson.group).distinct().order_by(BaseLesson.group)
        )
        return [g for (g,) in result.all()]
