import datetime

from sqlalchemy import Date, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TableNameMixin


class ScheduleFile(Base, TableNameMixin):
    date: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64))

    def __repr__(self):
        return f"<ScheduleFile {self.date} {self.content_hash[:8]}>"
