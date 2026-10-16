import datetime

from sqlalchemy import BigInteger, Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TableNameMixin


class ScheduleEdit(Base, TableNameMixin):
    """Журнал правок расписания: кто, что и когда менял.

    Позволяет показать историю и откатить последнюю правку.
    """

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    group: Mapped[str] = mapped_column(String(32), index=True)
    date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    para: Mapped[int | None] = mapped_column(Integer, nullable=True)
    layer: Mapped[str] = mapped_column(String(8), default="base")   # base | sub
    action: Mapped[str] = mapped_column(String(8), default="edit")  # add | edit | delete
    old_value: Mapped[str] = mapped_column(String(1024), default="")
    new_value: Mapped[str] = mapped_column(String(1024), default="")
    created_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self):
        return f"<ScheduleEdit {self.group} {self.layer}/{self.action} by {self.user_id}>"
