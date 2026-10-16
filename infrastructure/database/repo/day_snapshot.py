import datetime
import json

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert

from infrastructure.database.models import DaySnapshot
from infrastructure.database.repo.base import BaseRepo


class DaySnapshotRepo(BaseRepo):
    async def save(self, date: datetime.date, group: str, lessons) -> None:
        payload = json.dumps([
            {
                "para": getattr(l, "para", None),
                "subject": getattr(l, "subject", ""),
                "teacher": getattr(l, "teacher", ""),
                "room": getattr(l, "room", ""),
            }
            for l in lessons
        ], ensure_ascii=False)
        await self.session.execute(
            insert(DaySnapshot)
            .values(date=date, group=group, payload=payload,
                    created_at=datetime.datetime.now())
            .on_conflict_do_update(
                index_elements=["date", "group"],
                set_=dict(payload=payload, created_at=datetime.datetime.now()),
            )
        )
        await self.session.commit()

    async def get(self, date: datetime.date, group: str) -> list[dict]:
        result = await self.session.execute(
            select(DaySnapshot.payload).where(
                DaySnapshot.date == date, DaySnapshot.group == group)
        )
        payload = result.scalar_one_or_none()
        return json.loads(payload) if payload else []

    async def exists(self, date: datetime.date, group: str) -> bool:
        result = await self.session.execute(
            select(DaySnapshot.id).where(
                DaySnapshot.date == date, DaySnapshot.group == group).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def count(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(DaySnapshot))
        return result.scalar_one()
