import datetime
import json

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from infrastructure.database.models import DaySnapshot
from infrastructure.database.repo.base import BaseRepo


class DaySnapshotRepo(BaseRepo):
    async def save(self, date: datetime.date, group: str, lessons) -> None:
        # Восемь полей, а не четыре: без changed/action отменённая пара
        # при чтении архива выглядела бы как состоявшаяся — get_day_slots
        # кладёт в слот базовые subject/teacher, а признак держит в action.
        # comment и group тоже нужны: первый показывает пояснение
        # старосты, второй выбирает звонки (у 2–3 курса п2 кончается в
        # 12:20, у остальных в 12:40).
        payload = json.dumps([
            {
                "para": getattr(l, "para", None),
                "para_end": getattr(l, "para_end", None) or getattr(l, "para", None),
                "subject": getattr(l, "subject", ""),
                "teacher": getattr(l, "teacher", ""),
                "room": getattr(l, "room", ""),
                "changed": bool(getattr(l, "changed", False)),
                "action": getattr(l, "action", "") or "",
                "comment": getattr(l, "comment", "") or "",
                "time_note": getattr(l, "time_note", "") or "",
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

    async def get(self, date: datetime.date, group: str) -> list[dict] | None:
        """Снимок дня из архива или None, если его нет."""
        result = await self.session.execute(
            select(DaySnapshot.payload).where(
                DaySnapshot.date == date, DaySnapshot.group == group).limit(1)
        )
        payload = result.scalar_one_or_none()
        if payload is None:
            return None
        try:
            rows = json.loads(payload)
        except (TypeError, ValueError):
            return None
        return rows if isinstance(rows, list) else None

    async def get_dates_for_group(self, group: str) -> list[datetime.date]:
        """Даты, за которые для группы есть снимок."""
        result = await self.session.execute(
            select(DaySnapshot.date)
            .where(DaySnapshot.group == group)
            .distinct()
        )
        return sorted((d for (d,) in result.all()), reverse=True)

    async def exists(self, date: datetime.date, group: str) -> bool:
        result = await self.session.execute(
            select(DaySnapshot.id).where(
                DaySnapshot.date == date, DaySnapshot.group == group).limit(1)
        )
        return result.scalar_one_or_none() is not None
