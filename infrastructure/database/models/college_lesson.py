import datetime

from sqlalchemy import Date, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TableNameMixin


class CollegeLesson(Base, TableNameMixin):
    __table_args__ = (
        UniqueConstraint('date', 'group', 'para', name='uc_college_lesson'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime.date] = mapped_column(Date, index=True)
    group: Mapped[str] = mapped_column(String(32), index=True)
    para: Mapped[int] = mapped_column(Integer)
    para_end: Mapped[int] = mapped_column(Integer)
    subject: Mapped[str] = mapped_column(String(128))
    teacher: Mapped[str] = mapped_column(String(128), default="")
    room: Mapped[str] = mapped_column(String(64), default="")
    source_url: Mapped[str] = mapped_column(String(512), default="")

    def __repr__(self):
        return f"<CollegeLesson {self.date} {self.group} п{self.para} {self.subject}>"
