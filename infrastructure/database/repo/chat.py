import datetime
from typing import Optional

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert

from infrastructure.database.models import Chat
from infrastructure.database.repo.base import BaseRepo


class ChatRepo(BaseRepo):
    async def set_group(
        self, chat_id: int, title: str, group: str, status: str = "member",
    ) -> None:
        await self.session.execute(
            insert(Chat)
            .values(id=chat_id, title=title, group=group, status=status,
                    checked_at=datetime.datetime.now())
            .on_conflict_do_update(
                index_elements=["id"],
                set_=dict(title=title, group=group, status=status,
                          checked_at=datetime.datetime.now()),
            )
        )
        await self.session.commit()

    async def touch(self, chat_id: int, title: str = "") -> None:
        """Запомнить чат, где бот уже есть, но /setgroup ещё не вводили.

        Группа остаётся пустой: привязку делает админ, а факт присутствия
        бот знает сам — при добавлении в чат приходит my_chat_member.
        """
        values = {"id": chat_id, "title": title, "status": "member",
                  "checked_at": datetime.datetime.now()}
        upd = {"status": "member", "checked_at": datetime.datetime.now()}
        if title:
            values["title"] = title
            upd["title"] = title
        await self.session.execute(
            insert(Chat)
            .values(**values)
            .on_conflict_do_update(index_elements=["id"], set_=upd)
        )
        await self.session.commit()

    async def set_status(self, chat_id: int, status: str) -> None:
        """Отметить итог проверки getChatMember.

        Запись не удаляем: экран должен показать «бота выгнали», а не
        промолчать. Удаление оставлено на явную кнопку.
        """
        await self.session.execute(
            update(Chat)
            .where(Chat.id == chat_id)
            .values(status=status, checked_at=datetime.datetime.now())
        )
        await self.session.commit()

    async def get_all(self) -> list[Chat]:
        result = await self.session.execute(select(Chat).order_by(Chat.title))
        return list(result.scalars().all())

    async def get(self, chat_id: int) -> Optional[Chat]:
        result = await self.session.execute(select(Chat).where(Chat.id == chat_id))
        return result.scalar_one_or_none()

    async def remove(self, chat_id: int) -> None:
        """Отвязать чат. Без этого запись висела вечно: бота выгнали из
        группы, а рассылка каждый раз пыталась туда писать."""
        await self.session.execute(delete(Chat).where(Chat.id == chat_id))
        await self.session.commit()
