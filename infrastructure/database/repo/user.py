from typing import Optional

import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert

from infrastructure.database.models import User
from infrastructure.database.repo.base import BaseRepo


class UserRepo(BaseRepo):
    async def get_or_create_user(
            self,
            user_id: int,
            full_name: str,
            language: str,
            username: Optional[str] = None,
    ) -> User:
        insert_stmt = (
            insert(User)
            .values(
                id=user_id,
                username=username,
                full_name=full_name,
                language=language,
                last_seen=datetime.datetime.now(),
                subscribed=True,
                send_image=True,
                bell_notify=False,
            )
            .on_conflict_do_update(
                index_elements=[User.id],
                set_=dict(username=username, full_name=full_name, last_seen=datetime.datetime.now()),
            )
            .returning(User)
        )
        result = await self.session.execute(insert_stmt)
        await self.session.commit()
        return result.scalar_one()

    async def set_group(self, user_id: int, group: str) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(group=group)
        )
        await self.session.commit()

    async def set_subscribed(self, user_id: int, value: bool) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(subscribed=value)
        )
        await self.session.commit()

    async def set_bell_detail(self, user_id: int, value: str) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(bell_detail=value)
        )
        await self.session.commit()

    async def set_send_image(self, user_id: int, value: bool) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(send_image=value)
        )
        await self.session.commit()

    async def set_bell_notify(self, user_id: int, value: bool) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(bell_notify=value)
        )
        await self.session.commit()

    async def get_subscribed(self) -> list[User]:
        result = await self.session.execute(
            select(User).where(User.subscribed == True, User.group.is_not(None))  # noqa: E712
        )
        return list(result.scalars().all())

    async def get_bell_subscribers(self) -> list[User]:
        result = await self.session.execute(
            select(User).where(
                User.subscribed == True,  # noqa: E712
                User.bell_notify == True,  # noqa: E712
                User.group.is_not(None),
            )
        )
        return list(result.scalars().all())

    async def get_all(self) -> list[User]:
        result = await self.session.execute(select(User))
        return list(result.scalars().all())

    async def get_by_group(self, group: Optional[str]) -> list[User]:
        cond = User.group.is_(None) if group is None else (User.group == group)
        result = await self.session.execute(select(User).where(cond).order_by(User.created_at))
        return list(result.scalars().all())
