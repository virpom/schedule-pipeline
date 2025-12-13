import datetime
from dataclasses import dataclass
from enum import IntEnum

DAYS_OF_WEEK = ("ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС")


class WeekDay(IntEnum):
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6

    @property
    def short_name(self) -> str:
        return DAYS_OF_WEEK[self]

    @classmethod
    def from_short_name(cls, short_name: str):
        idx = DAYS_OF_WEEK.index(short_name)
        return cls(idx)


class Semester(IntEnum):
    FALL = 1
    SPRING = 2


@dataclass
class Period:
    year_start: int
    year_end: int
    semester: Semester

    def get_start_date(self) -> datetime.date:
        if self.semester == Semester.FALL:
            start_date = datetime.date(self.year_start, 9, 1)
        else:
            start_date = datetime.date(self.year_end, 2, 10)

        if start_date.weekday() == WeekDay.SUNDAY:
            start_date += datetime.timedelta(days=1)
        return start_date