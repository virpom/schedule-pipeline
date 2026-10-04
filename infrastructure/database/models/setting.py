from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TableNameMixin


class Setting(Base, TableNameMixin):
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(128))

    def __repr__(self):
        return f"<Setting {self.key}={self.value}>"
