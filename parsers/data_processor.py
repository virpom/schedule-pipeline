import datetime
import re
from dataclasses import dataclass
from typing import Generator

import pandas as pd

from common.academic_calendar import Period, WeekDay, Semester
from infrastructure.database.models.lesson import SessionType
from parsers.pdf_parser import ScheduleMetadata


@dataclass
class StreamInfo:
    code: str
    course: int
    specialization_code: str
    specialization_title: str


@dataclass
class LessonInfo:
    session_type: SessionType
    title: str
    start_time: datetime.datetime
    end_time: datetime.datetime
    group_code: str


@dataclass
class StreamLessonsInfo:
    stream: StreamInfo
    lessons: list[LessonInfo]


class ScheduleParser:
    def __init__(self, metadata: ScheduleMetadata, schedule_data: pd.DataFrame):
        self.metadata = metadata
        self.schedule_data = schedule_data

    def parse_schedule(self) -> StreamLessonsInfo:
        lessons = []
        for _, row in self.schedule_data.iterrows():
            day_of_week_code = row["День недели"]
            time_intervals = row["Время"].split()

            for time_str in time_intervals:
                start_time, end_time = time_str.split('-')
                if self.metadata.session_type == SessionType.PRACTICE:
                    lessons.extend(self._parse_practice(row, day_of_week_code, start_time, end_time))
                elif self.metadata.session_type == SessionType.LECTURE:
                    lessons.extend(self._parse_lecture(row, day_of_week_code, start_time, end_time))
        stream = self._get_stream_info()
        return StreamLessonsInfo(stream, lessons)

    def _parse_practice(
            self,
            row: pd.Series,
            day_of_week_code: str,
            start_time: str,
            end_time: str,
    ) -> Generator[LessonInfo, None, None]:
        for group_code in self.schedule_data.columns[2:]:
            lesson_string = row[group_code]
            if pd.isna(lesson_string):
                continue
            lessons = self._parse_lesson_string(lesson_string)
            yield from self._create_lessons(lessons, day_of_week_code, start_time, end_time, group_code)

    def _parse_lecture(
            self,
            row: pd.Series,
            day_of_week_code: str,
            start_time: str,
            end_time: str,
    ) -> Generator[LessonInfo, None, None]:
        lesson_title = row["Предмет"]
        weeks_raw = row["Недели"]
        weeks = self._parse_week_nums(weeks_raw)
        yield from self._create_lessons([(lesson_title, weeks)], day_of_week_code, start_time, end_time, group_code="0")

    def _create_lessons(
            self, lessons_data, day_of_week_code, start_time, end_time, group_code
    ) -> Generator[LessonInfo, None, None]:
        for title, week_nums in lessons_data:
            for week_num in week_nums:
                yield LessonInfo(
                    session_type=self.metadata.session_type,
                    title=title,
                    start_time=self._parse_datetime(day_of_week_code, start_time, week_num),
                    end_time=self._parse_datetime(day_of_week_code, end_time, week_num),
                    group_code=group_code,
                )

    def _parse_lesson_string(self, lesson_str: str) -> list[tuple[str, list[int]]]:
        if not lesson_str:
            return []
        pattern = r"\b(.+?):\s?(\d[\d\s,-]+)\s?(?:нед|н)?\.?"
        matches = re.findall(pattern, lesson_str, re.I)
        return [(match[0].strip(), self._parse_week_nums(match[1])) for match in matches]

    def _parse_week_nums(self, weeks_raw: str) -> list[int]:
        weeks_raw = weeks_raw.replace(" ", "").strip(",.нед")
        weeks = []
        for part in weeks_raw.split(","):
            if not part:
                continue
            if "-" in part:
                start, end = map(int, part.split("-"))
                weeks.extend(range(start, end + 1))
            else:
                weeks.append(int(part))
        return weeks

    def _parse_datetime(self, day_of_week_code: str, time_str: str, week_num: int) -> datetime.datetime:
        semester_start = self.metadata.period.get_start_date()
        days_to_add = (week_num - 1) * 7 + WeekDay.from_short_name(day_of_week_code)
        target_date = semester_start + datetime.timedelta(days=days_to_add)
        hours, minutes = map(int, time_str.split(":"))
        return datetime.datetime(
            year=target_date.year,
            month=target_date.month,
            day=target_date.day,
            hour=hours,
            minute=minutes,
        )

    def _get_stream_info(self) -> StreamInfo:
        return StreamInfo(
            code=self.metadata.stream_code,
            course=self.metadata.course,
            specialization_code=self.metadata.specialization_code,
            specialization_title=self.metadata.specialization_title,
        )


if __name__ == "__main__":
    metadata = ScheduleMetadata(
        session_type=SessionType.LECTURE,
        period=Period(2024, 2025, Semester.FALL),
        course=2,
        specialization_code="09.03.04",
        specialization_title="Программная инженерия",
        stream_code="А",
    )
    data = pd.DataFrame(
        [
            {"День недели": "ПН", "Время": "10:00-11:30", "Предмет": "Математика", "Недели": "1-3, 5"},
            {"День недели": "СР", "Время": "12:00-13:30", "Предмет": "Физика", "Недели": "2, 4"},
        ]
    )
    parser = ScheduleParser(metadata, data)
    for lesson in parser.parse_schedule().lessons:
        print(lesson)

    metadata = ScheduleMetadata(
        session_type=SessionType.PRACTICE,
        period=Period(2024, 2025, Semester.FALL),
        course=2,
        specialization_code="09.03.04",
        specialization_title="Программная инженерия",
        stream_code="А",
    )
    data = pd.DataFrame(
        [
            {"День недели": "ПН", "Время": "10:00-11:30", "153 А": "Математика: 2 н.", "64 Б": "Биология: 2-4 н."},
            {"День недели": "СР", "Время": "12:00-13:30", "153 А": "Физика: 1, 3-5 н.\nХимия: 2 н."},
        ]
    )
    parser = ScheduleParser(metadata, data)
    for lesson in parser.parse_schedule().lessons:
        print(lesson)
