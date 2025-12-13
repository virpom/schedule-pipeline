from sqlalchemy import String, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TableNameMixin


class Stream(Base, TableNameMixin):
    __table_args__ = (
        UniqueConstraint("code", "course", "specialization_code", name="uc_stream"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    code: Mapped[str] = mapped_column(String(8))
    course: Mapped[int] = mapped_column(Integer)
    specialization_code: Mapped[str] = mapped_column(String(16))
    specialization_title: Mapped[str] = mapped_column(String(128))

    lessons: Mapped[list["Lesson"]] = relationship("Lesson", back_populates="stream")

    def __repr__(self) -> str:
        return f"<Stream ({self.specialization_code}, {self.course} course, {self.code})>"
