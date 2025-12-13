import datetime
import enum

from sqlalchemy import Enum, DateTime, String, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import mapped_column, relationship, Mapped

from .base import Base, TableNameMixin


class SessionType(enum.Enum):
    LECTURE = "ЛЕКЦИЯ"
    PRACTICE = "ПРАКТИКА"
    UNKNOWN = "НЕИЗВЕСТНО"


class Lesson(Base, TableNameMixin):
    __table_args__ = (
        UniqueConstraint("title", "start_time", "group_code", "stream_id",
                         name="uc_class_session"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_type: Mapped[SessionType] = mapped_column(
        Enum(SessionType, values_callable=lambda obj: [e.value for e in obj]),
        server_default=SessionType.UNKNOWN.value,
    )
    title: Mapped[str] = mapped_column(String(128))
    start_time: Mapped[datetime.datetime] = mapped_column(DateTime)
    end_time: Mapped[datetime.datetime] = mapped_column(DateTime)
    group_code: Mapped[str] = mapped_column(String(8), ForeignKey("student_group.code"))
    stream_id: Mapped[str] = mapped_column(String(3), ForeignKey("stream.id"))

    student_group: Mapped["StudentGroup"] = relationship("StudentGroup", back_populates="lessons")
    stream: Mapped["Stream"] = relationship("Stream", back_populates="lessons")

    def __repr__(self) -> str:
        return f"<Lesson {self.student_group}:{self.title} [{self.start_time} - {self.end_time}]>"
