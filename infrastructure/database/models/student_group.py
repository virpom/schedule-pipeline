from sqlalchemy import String, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TableNameMixin


class StudentGroup(Base, TableNameMixin):
    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    stream_id: Mapped[str] = mapped_column(Integer, ForeignKey("stream.id"))

    stream: Mapped["Stream"] = relationship("Stream")
    lessons: Mapped[list["Lesson"]] = relationship("Lesson", back_populates="student_group")

    def __repr__(self):
        return f"<StudentGroup ({self.code}, {self.stream.stream})>"
