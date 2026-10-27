import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert

from infrastructure.database.models import BellReminder
from infrastructure.database.repo.base import BaseRepo


class BellReminderRepo(BaseRepo):
    async def is_sent(self, user_id: int, date: datetime.date, event_key: str) -> bool:
        result = await self.session.execute(
            select(BellReminder.id).where(
                BellReminder.user_id == user_id,
                BellReminder.date == date,
                BellReminder.event_key == event_key,
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def mark_sent(self, user_id: int, date: datetime.date, event_key: str) -> None:
        await self.session.execute(
            insert(BellReminder).values(user_id=user_id, date=date, event_key=event_key)
            .on_conflict_do_nothing(index_elements=["user_id", "date", "event_key"])
        )
        await self.session.commit()

    async def delete_before(self, date: datetime.date) -> int:
        """Убрать отметки за дни до указанного.

        Строго `<`, не `<=`: при перезапуске в течение дня человек не
        должен получить повторные звонки. `is_sent` проверяет только
        сегодняшнюю дату, так что вчерашние строки мёртвые — на проде
        их 60% из 456.
        """
        result = await self.session.execute(
            delete(BellReminder).where(BellReminder.date < date)
        )
        await self.session.commit()
        return result.rowcount or 0
