import datetime

from sqlalchemy import Date, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TableNameMixin


class Substitution(Base, TableNameMixin):
    """Замена — временное изменение на конкретную дату.

    Выдаётся на один день вперёд. Перекрывает базовое расписание.
    """

    __table_args__ = (
        UniqueConstraint('date', 'group', 'para', name='uc_substitution'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime.date] = mapped_column(Date, index=True)
    group: Mapped[str] = mapped_column(String(32), index=True)
    para: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(8))        # replace | cancel | add
    subject: Mapped[str] = mapped_column(String(128), default="")
    teacher: Mapped[str] = mapped_column(String(128), default="")
    room: Mapped[str] = mapped_column(String(64), default="")
    comment: Mapped[str] = mapped_column(String(256), default="")
    source: Mapped[str] = mapped_column(String(8), default="manual")
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self):
        return f"<Substitution {self.date} {self.group} п{self.para} {self.action}>"
