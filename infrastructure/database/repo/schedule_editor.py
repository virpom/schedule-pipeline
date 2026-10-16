import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert

from infrastructure.database.models import ScheduleEditor
from infrastructure.database.repo.base import BaseRepo


class ScheduleEditorRepo(BaseRepo):
    async def get_group_for(self, user_id: int) -> str | None:
        """Группа, которую пользователь может редактировать (или None)."""
        result = await self.session.execute(
            select(ScheduleEditor.group).where(
                ScheduleEditor.user_id == user_id,
                ScheduleEditor.is_active == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def grant(self, user_id: int, group: str, granted_by: int | None = None) -> None:
        await self.session.execute(
            insert(ScheduleEditor)
            .values(user_id=user_id, group=group, granted_by=granted_by,
                    granted_at=datetime.datetime.now(), is_active=True)
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_=dict(group=group, granted_by=granted_by,
                          granted_at=datetime.datetime.now(), is_active=True),
            )
        )
        await self.session.commit()

    async def revoke(self, user_id: int) -> None:
        await self.session.execute(
            update(ScheduleEditor)
            .where(ScheduleEditor.user_id == user_id)
            .values(is_active=False)
        )
        await self.session.commit()

    async def get_all(self) -> list[ScheduleEditor]:
        result = await self.session.execute(
            select(ScheduleEditor).where(ScheduleEditor.is_active == True)  # noqa: E712
        )
        return list(result.scalars().all())
