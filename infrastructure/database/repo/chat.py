from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from infrastructure.database.models import Chat
from infrastructure.database.repo.base import BaseRepo


class ChatRepo(BaseRepo):
    async def set_group(self, chat_id: int, title: str, group: str) -> None:
        await self.session.execute(
            insert(Chat)
            .values(id=chat_id, title=title, group=group)
            .on_conflict_do_update(
                index_elements=["id"],
                set_=dict(title=title, group=group),
            )
        )
        await self.session.commit()

    async def get_all(self) -> list[Chat]:
        result = await self.session.execute(select(Chat))
        return list(result.scalars().all())
