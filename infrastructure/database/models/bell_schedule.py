import datetime

from sqlalchemy import Integer, String, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TableNameMixin


class BellSchedule(Base, TableNameMixin):
    __table_args__ = (
        UniqueConstraint('day_type', 'course_group', 'para', name='uc_bell_schedule'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day_type: Mapped[str] = mapped_column(String(16))       # MONDAY | OTHER
    course_group: Mapped[str] = mapped_column(String(16))   # ALL | I_IV | II_III
    para: Mapped[int] = mapped_column(Integer)              # 0 = «Разговоры о важном»
    start: Mapped[datetime.time] = mapped_column(Time)      # первый академ. час: начало
    h1_end: Mapped[datetime.time] = mapped_column(Time)     # первый академ. час: конец
    h2_start: Mapped[datetime.time] = mapped_column(Time)   # второй академ. час: начало
    end: Mapped[datetime.time] = mapped_column(Time)        # второй академ. час: конец

    def __repr__(self):
        return f"<BellSchedule {self.day_type}/{self.course_group} п{self.para} {self.start}-{self.end}>"
