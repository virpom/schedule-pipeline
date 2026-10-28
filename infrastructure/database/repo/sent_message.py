import datetime

from sqlalchemy import delete, func, select

from infrastructure.database.models import SentMessage
from infrastructure.database.repo.base import BaseRepo


class SentMessageRepo(BaseRepo):
    async def add_batch(self, rows: list[tuple[int, int, str]]) -> None:
        """Записать пачку доставленных сообщений ``(chat_id, message_id, kind)``.

        Пачкой, а не строкой на каждый: при инциденте бывает тысяча
        вставок за минуту, и тысяча отдельных коммитов в SQLite — это
        тысяча синхронизаций диска.
        """
        if not rows:
            return
        now = datetime.datetime.now()
        self.session.add_all([
            SentMessage(chat_id=chat_id, message_id=message_id, kind=kind,
                        created_at=now)
            for chat_id, message_id, kind in rows
        ])
        await self.session.commit()

    async def latest_batch(self, kind: str = "schedule",
                           within_hours: float = 48.0):
        """Последняя рассылка: ``(created_at, [(chat_id, message_id), ...])``.

        Берём строки «пачкой одного момента»: рассылка пишет все блоки
        с одним ``created_at``, поэтому достаточно последней записи
        нужного вида. Старше 48 часов Bot API удалить не даёт.
        """
        since = datetime.datetime.now() - datetime.timedelta(hours=within_hours)
        last = (await self.session.execute(
            select(SentMessage.created_at)
            .where(SentMessage.kind == kind, SentMessage.created_at >= since)
            .order_by(SentMessage.created_at.desc())
            .limit(1))).scalar_one_or_none()
        if last is None:
            return None
        rows = (await self.session.execute(
            select(SentMessage.chat_id, SentMessage.message_id)
            .where(SentMessage.kind == kind,
                   SentMessage.created_at == last)
            .order_by(SentMessage.id))).all()
        return last, [(c, m) for c, m in rows]

    async def delete_before(self, moment: datetime.datetime) -> int:
        result = await self.session.execute(
            delete(SentMessage).where(SentMessage.created_at < moment))
        await self.session.commit()
        return result.rowcount or 0

    async def purge_older(self, hours: float = 48.0) -> int:
        """Удалить id старше ``hours``: их Bot API всё равно не отзовёт."""
        return await self.delete_before(
            datetime.datetime.now() - datetime.timedelta(hours=hours))

    async def purge_older_moment(self, moment: datetime.datetime) -> int:
        """Удалить всё, что старше (или ровно) ``moment`` — после отзыва."""
        return await self.delete_before(moment + datetime.timedelta(microseconds=1))

    async def count(self) -> int:
        return (await self.session.execute(
            select(func.count()).select_from(SentMessage))).scalar_one()
