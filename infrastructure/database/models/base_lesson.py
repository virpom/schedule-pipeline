import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TableNameMixin


class BaseLesson(Base, TableNameMixin):
    """Базовое (постоянное) расписание группы.

    Не привязано к конкретной дате: описывает, какая пара стоит в
    определённый день недели на чётной/нечётной неделе.
    Накладывается на Substitution, чтобы получить итог дня.
    """

    __table_args__ = (
        UniqueConstraint('group', 'week_parity', 'weekday', 'para',
                         name='uc_base_lesson'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group: Mapped[str] = mapped_column(String(32), index=True)
    week_parity: Mapped[str] = mapped_column(String(4))   # ODD | EVEN | ANY
    weekday: Mapped[int] = mapped_column(Integer)         # 1..7 (Пн..Вс)
    para: Mapped[int] = mapped_column(Integer)            # 1..5
    subject: Mapped[str] = mapped_column(String(128))
    teacher: Mapped[str] = mapped_column(String(128), default="")
    room: Mapped[str] = mapped_column(String(64), default="")
    source: Mapped[str] = mapped_column(String(8), default="manual")  # site | manual
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self):
        return f"<BaseLesson {self.group} {self.week_parity}/wd{self.weekday} п{self.para}>"
