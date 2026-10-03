from typing import Optional

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
            )
            .on_conflict_do_update(
                index_elements=[User.id],
                set_=dict(username=username, full_name=full_name),
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

    async def get_subscribed(self) -> list[User]:
        result = await self.session.execute(
            select(User).where(User.subscribed == True, User.group.is_not(None))  # noqa: E712
        )
        return list(result.scalars().all())
