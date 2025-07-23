from typing import Optional

from sqlalchemy import BigInteger, Boolean, String, ForeignKey
from sqlalchemy import text, true
from sqlalchemy.orm import mapped_column, relationship, Mapped

from .base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    full_name: Mapped[str] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    language: Mapped[str] = mapped_column(String(10), server_default=text("'ru'"))
    group_code: Mapped[Optional[str]] = mapped_column(String(8), ForeignKey("student_group.code"), nullable=True)

    student_group: Mapped["StudentGroup"] = relationship("StudentGroup")

    def __repr__(self):
        return f"<User {self.id} {self.username} {self.full_name} {self.student_group}>"
