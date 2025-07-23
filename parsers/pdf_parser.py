import re
from dataclasses import dataclass

import pandas as pd
import pdfplumber
from pdfplumber.page import Page, T_table_settings

from common.academic_calendar import DAYS_OF_WEEK, Period, Semester
from infrastructure.database.models.lesson import SessionType


@dataclass
class ScheduleMetadata:
    session_type: SessionType
    period: Period
    course: int
    specialization_code: str
    specialization_title: str
    stream_code: str


class HeaderParser:
    PATTERNS = {
        "session_type": r"(семинарского|лекционного) типа",
        "semester": r"(осенний|весенний) семестр",
        "year_range": r"(\d{4}/\d{4}) учебного года",
        "course_data": r"(\d+) курс",
        "specialization_data": "(?:специальность|направление подготовки) ([\d.]+) (?:- )?([A-ZА-ЯЁ,]+)\W",
        "stream_code": r'ПОТОК "\s?([0-9A-ZА-ЯЁ]+)\s?"'
    }

    @staticmethod
    def parse_header(text: str) -> ScheduleMetadata:
        text = HeaderParser.prepare_content(text)
        matches = {key: re.search(pattern, text, flags=re.IGNORECASE)
                   for key, pattern in HeaderParser.PATTERNS.items()}
        missing = [key for key, match in matches.items() if not match]
        if missing and (missing != ["stream_code"] or "ПОТОКИ" in text):
            raise ValueError(f"Cannot parse schedule header info: {', '.join(missing)}")

        session_type_map = {"семинарского": SessionType.PRACTICE, "лекционного": SessionType.LECTURE}
        session_type = session_type_map.get(matches["session_type"].group(1), SessionType.UNKNOWN)

        semester = Semester.FALL if matches['semester'].group(1) == "осенний" else Semester.SPRING
        year_start, year_end = map(int, matches["year_range"].group(1).split("/"))

        course = matches["course_data"].group(1)
        speciality_code, speciality_title = matches["specialization_data"].groups()
        if matches["stream_code"]:
            stream_code = matches["stream_code"].group(1).replace("E", "Е")
        else:
            stream_code = "А"

        return ScheduleMetadata(
            session_type=session_type,
            period=Period(year_start, year_end, semester),
            course=int(course),
            specialization_code=speciality_code,
            specialization_title=speciality_title.strip(),
            stream_code=stream_code
        )

    @staticmethod
    def prepare_content(text: str) -> str:
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\s?([?:,])\s?([A-ZА-ЯЁ\d])", "\g<1> \g<2>", text, flags=re.IGNORECASE)
        return text


class TableParser:
    @staticmethod
    def find_header_row_idx(table: list[list[str | None]]) -> int:
        for idx, row in enumerate(table[:5]):  # Проверяем первые 5 строк
            if all(col in row for col in ["Предмет", "Недели", "Павильон"]):
                return idx
            if len(row) > 1 and all(re.match(r"\d+\s?[A-ZА-ЯЁ]", col) for col in row if col):
                return idx
            if ["Предмет", "Время"] == row[:2] and all(re.match(r"\d+\s?[A-ZА-ЯЁ]?", col) for col in row[2:] if col):
                return idx
        raise ValueError("Cannot find a line with correct column names")

    @staticmethod
    def parse_schedule_table(table: list[list[str | None]]) -> pd.DataFrame:
        header_idx = TableParser.find_header_row_idx(table)

        first_columns = ["День недели", "Время"]
        if "Предмет" in table[header_idx]:
            first_columns.append("Предмет")
        columns = first_columns + table[header_idx][len(first_columns):]
        df = pd.DataFrame(table[header_idx + 1:], columns=columns)

        df = df.replace(r"\s+", " ", regex=True)
        df[first_columns] = df[first_columns].replace(r'^\s?$', float('NaN'), regex=True)
        df = df.drop(columns=[None], errors='ignore').dropna(how='all')
        df = df.rename(columns=lambda x: re.sub(r"(\d)([A-ZА-ЯЁ])", r"\1 \2", x, re.I))
        df["Время"] = df["Время"].replace({r"\s?-\s?": "-", r"\.": ":"}, regex=True)
        df = df[df["День недели"].isin(DAYS_OF_WEEK) | df["День недели"].isnull()].ffill()

        return df


class PDFScheduleExtractor:
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path

    def extract_schedule(self) -> tuple[ScheduleMetadata, pd.DataFrame]:
        with pdfplumber.open(self.pdf_path) as pdf:
            table_settings = {"text_y_tolerance": 2, "text_use_text_flow": True}
            metadata = self.extract_metadata(pdf.pages[0])
            schedule_table = self.extract_table(pdf.pages, table_settings)
            return metadata, schedule_table

    @staticmethod
    def extract_metadata(page: Page) -> ScheduleMetadata:
        text = page.extract_text()
        return HeaderParser.parse_header(text)

    @staticmethod
    def extract_table(pages: list[Page], table_settings: T_table_settings | None = None) -> pd.DataFrame:
        tables = [table
                  for page in pages
                  for table in page.extract_tables(table_settings)]
        if not tables:
            raise ValueError("Cannot extract schedule table")
        combined_table = [row for table in tables for row in table]
        return TableParser.parse_schedule_table(combined_table)


if __name__ == '__main__':
    pdf_path = "../schedule_data\Лекции_1_СД_Осень_2024-2025_ОЧ_ЗАОЧ.xlsx.pdf"

    extractor = PDFScheduleExtractor(pdf_path)
    metadata, schedule_df = extractor.extract_schedule()

    print("Метаданные:")
    print(metadata)
    print("\nРасписание:")
    print(schedule_df.head(5))
