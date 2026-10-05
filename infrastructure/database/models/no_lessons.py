import datetime

from sqlalchemy import Date, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TableNameMixin


class NoLessons(Base, TableNameMixin):
    __table_args__ = (
        UniqueConstraint('date', 'group', name='uc_no_lessons'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime.date] = mapped_column(Date, index=True)
    group: Mapped[str] = mapped_column(String(32), index=True)
    note: Mapped[str] = mapped_column(String(256), default="")

    def __repr__(self):
        return f"<NoLessons {self.date} {self.group}>"
