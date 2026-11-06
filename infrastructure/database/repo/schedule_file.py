import datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from infrastructure.database.models import ScheduleFile
from infrastructure.database.repo.base import BaseRepo


class ScheduleFileRepo(BaseRepo):
    async def get_hash(self, date: datetime.date) -> str | None:
        result = await self.session.execute(
            select(ScheduleFile.content_hash).where(ScheduleFile.date == date)
        )
        return result.scalar_one_or_none()

    async def get_dates(self, start: datetime.date, end: datetime.date) -> set[datetime.date]:
        """Даты, по которым есть отметка о публикации.

        Нужно материализации: день без пар не попадает в digest_by_date
        (там нет строк), и без этой проверки он пересобирался бы каждый
        цикл — поллер зовёт materialize каждые 5 минут.
        """
        result = await self.session.execute(
            select(ScheduleFile.date).where(
                ScheduleFile.date >= start, ScheduleFile.date <= end)
        )
        return {d for (d,) in result.all()}

    async def set_hash(self, date: datetime.date, content_hash: str) -> None:
        await self.session.execute(
            insert(ScheduleFile)
            .values(date=date, content_hash=content_hash)
            .on_conflict_do_update(index_elements=["date"], set_=dict(content_hash=content_hash))
        )
        await self.session.commit()
