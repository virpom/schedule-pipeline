import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TableNameMixin


class SentMessage(Base, TableNameMixin):
    """Что бот отправил и когда — чтобы ошибочную рассылку можно было отозвать.

    Bot API не даёт удалить сообщение старше 48 часов, поэтому строки
    старше двух суток чистит poller: дальше они бесполезны.
    """

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    message_id: Mapped[int] = mapped_column(Integer)
    # schedule | bell | edit | broadcast
    kind: Mapped[str] = mapped_column(String(16), default="")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, index=True, default=datetime.datetime.now)

    def __repr__(self):
        return f"<SentMessage {self.chat_id}:{self.message_id} {self.kind}>"
