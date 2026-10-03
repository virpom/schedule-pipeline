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

    async def set_hash(self, date: datetime.date, content_hash: str) -> None:
        await self.session.execute(
            insert(ScheduleFile)
            .values(date=date, content_hash=content_hash)
            .on_conflict_do_update(index_elements=["date"], set_=dict(content_hash=content_hash))
        )
        await self.session.commit()
