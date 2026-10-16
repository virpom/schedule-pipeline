import datetime

from sqlalchemy import Date, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TableNameMixin


class DaySnapshot(Base, TableNameMixin):
    """Архив: фактическое расписание группы на прошедший день.

    Снимается по окончании учебного дня (база + замены на тот момент).
    """

    __table_args__ = (
        UniqueConstraint('date', 'group', name='uc_day_snapshot'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime.date] = mapped_column(Date, index=True)
    group: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[str] = mapped_column(String(4096), default="")  # JSON пар
    created_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self):
        return f"<DaySnapshot {self.date} {self.group}>"
