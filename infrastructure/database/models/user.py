import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, String
from sqlalchemy import text, true
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    full_name: Mapped[str] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    language: Mapped[str] = mapped_column(String(10), server_default=text("'ru'"))
    group: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    subscribed: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))
    bell_detail: Mapped[str] = mapped_column(String(16), server_default=text("'brief'"))
    send_image: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))
    bell_notify: Mapped[bool] = mapped_column(Boolean, server_default=text("0"))
    last_seen: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self):
        return f"<User {self.id} {self.username} {self.group}>"
