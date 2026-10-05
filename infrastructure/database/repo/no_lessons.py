import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert

from infrastructure.database.models import NoLessons
from infrastructure.database.repo.base import BaseRepo


class NoLessonsRepo(BaseRepo):
    async def get_note(self, date: datetime.date, group: str) -> str | None:
        result = await self.session.execute(
            select(NoLessons.note).where(NoLessons.date == date, NoLessons.group == group).limit(1)
        )
        return result.scalar_one_or_none()

    async def replace_date(self, date: datetime.date, rows: list[dict]) -> None:
        await self.session.execute(delete(NoLessons).where(NoLessons.date == date))
        if rows:
            await self.session.execute(insert(NoLessons).values(rows))
        await self.session.commit()
