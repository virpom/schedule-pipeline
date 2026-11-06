import datetime
from typing import Optional

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class Chat(Base, TimestampMixin):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(128), default="")
    group: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # «member» / «left» / «kicked» — по последней проверке getChatMember.
    # None значит «ещё не проверяли»: старые строки такие же.
    status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    checked_at: Mapped[Optional[datetime.datetime]] = mapped_column(nullable=True)

    def __repr__(self):
        return f"<Chat {self.id} {self.group}>"
