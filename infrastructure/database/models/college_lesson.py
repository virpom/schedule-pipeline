import datetime

from sqlalchemy import Boolean, Date, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TableNameMixin


class CollegeLesson(Base, TableNameMixin):
    """Пары, скачанные с сайта (режим «временного» расписания).

    Остаётся как архив данных, собранных парсером до перехода на модель
    BaseLesson + Substitution. Поле source отличает их от ручных правок.
    """

    # NB: в боевой БД уникального индекса нет; согласованность держит
    # replace_date(), который сначала удаляет все пары за дату.
    __table_args__ = ()

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime.date] = mapped_column(Date, index=True)
    group: Mapped[str] = mapped_column(String(32), index=True)
    para: Mapped[int] = mapped_column(Integer)
    para_end: Mapped[int] = mapped_column(Integer)
    subject: Mapped[str] = mapped_column(String(128))
    teacher: Mapped[str] = mapped_column(String(128), default="")
    room: Mapped[str] = mapped_column(String(64), default="")
    source_url: Mapped[str] = mapped_column(String(512), default="")
    source: Mapped[str] = mapped_column(String(8), server_default=text("'site'"))
    # Пара пришла из листка замен. Нужен, чтобы пометить её значком в
    # расписании: студент должен видеть, что это не по постоянному плану.
    changed: Mapped[bool] = mapped_column(Boolean, default=False,
                                          server_default=text("0"))

    def __repr__(self):
        return f"<CollegeLesson {self.date} {self.group} п{self.para} {self.subject}>"
