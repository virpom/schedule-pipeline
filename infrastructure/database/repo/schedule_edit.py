import datetime
import json

from sqlalchemy import delete, select

from infrastructure.database.models import ScheduleEdit
from infrastructure.database.repo.base import BaseRepo


def _dump(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:1024]
    return json.dumps(value, ensure_ascii=False, default=str)[:1024]


class ScheduleEditRepo(BaseRepo):
    async def log(self, group: str, layer: str, action: str,
                  user_id: int | None = None, date: datetime.date | None = None,
                  para: int | None = None, old_value=None, new_value=None) -> None:
        self.session.add(ScheduleEdit(
            user_id=user_id, group=group, date=date, para=para,
            layer=layer, action=action,
            old_value=_dump(old_value), new_value=_dump(new_value),
            created_at=datetime.datetime.now(),
        ))
        await self.session.commit()

    async def get_recent(self, group: str, limit: int = 10) -> list[ScheduleEdit]:
        result = await self.session.execute(
            select(ScheduleEdit)
            .where(ScheduleEdit.group == group)
            .order_by(ScheduleEdit.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def delete(self, edit_id: int) -> None:
        """Убрать запись из журнала после отката.

        Без этого повторное нажатие «Откатить» откатывало ту же самую
        правку снова: журнал не двигался, и кнопка выглядела сломанной.
        """
        await self.session.execute(
            delete(ScheduleEdit).where(ScheduleEdit.id == edit_id))
        await self.session.commit()

    async def get_last(self, group: str, user_id: int | None = None) -> ScheduleEdit | None:
        query = select(ScheduleEdit).where(ScheduleEdit.group == group)
        if user_id is not None:
            query = query.where(ScheduleEdit.user_id == user_id)
        result = await self.session.execute(query.order_by(ScheduleEdit.id.desc()).limit(1))
        return result.scalar_one_or_none()
