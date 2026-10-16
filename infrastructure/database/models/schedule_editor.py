import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TableNameMixin


class ScheduleEditor(Base, TableNameMixin):
    """Право редактировать расписание группы (староста).

    Один редактор — одна группа. Отзывается через is_active=0.
    """

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    group: Mapped[str] = mapped_column(String(32), index=True)
    granted_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    granted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))

    def __repr__(self):
        return f"<ScheduleEditor {self.user_id} -> {self.group}>"
