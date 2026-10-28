from sqlalchemy import delete, select
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

    async def remove(self, chat_id: int) -> None:
        """Отвязать чат. Без этого запись висела вечно: бота выгнали из
        группы, а рассылка каждый раз пыталась туда писать."""
        await self.session.execute(delete(Chat).where(Chat.id == chat_id))
        await self.session.commit()
