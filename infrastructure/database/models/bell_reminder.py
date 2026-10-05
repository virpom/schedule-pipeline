import datetime

from sqlalchemy import BigInteger, Date, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TableNameMixin


class BellReminder(Base, TableNameMixin):
    __table_args__ = (
        UniqueConstraint('user_id', 'date', 'event_key', name='uc_bell_reminder'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    date: Mapped[datetime.date] = mapped_column(Date, index=True)
    event_key: Mapped[str] = mapped_column(String(64))

    def __repr__(self):
        return f"<BellReminder {self.user_id} {self.date} {self.event_key}>"
