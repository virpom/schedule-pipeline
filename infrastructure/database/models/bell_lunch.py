import datetime

from sqlalchemy import Integer, String, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TableNameMixin


class BellLunch(Base, TableNameMixin):
    __table_args__ = (
        UniqueConstraint('day_type', 'course_group', name='uc_bell_lunch'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day_type: Mapped[str] = mapped_column(String(16))       # MONDAY | OTHER
    course_group: Mapped[str] = mapped_column(String(16))   # I_IV | II_III
    lunch_start: Mapped[datetime.time] = mapped_column(Time)
    lunch_end: Mapped[datetime.time] = mapped_column(Time)
    para: Mapped[int] = mapped_column(Integer)              # к какой паре привязан обед
    position: Mapped[str] = mapped_column(String(8))        # inside | after

    def __repr__(self):
        return f"<BellLunch {self.day_type}/{self.course_group} {self.lunch_start}-{self.lunch_end} ({self.position} п{self.para})>"
