import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TableNameMixin


class BaseLesson(Base, TableNameMixin):
    """Базовое (постоянное) расписание группы.

    Не привязано к конкретной дате: описывает, какая пара стоит в
    определённый день недели на чётной/нечётной неделе.
    Накладывается на Substitution, чтобы получить итог дня.
    """

    __table_args__ = (
        UniqueConstraint('group', 'week_parity', 'weekday', 'para', 'weeks',
                         name='uc_base_lesson'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group: Mapped[str] = mapped_column(String(32), index=True)
    week_parity: Mapped[str] = mapped_column(String(4))   # ODD | EVEN | ANY
    weekday: Mapped[int] = mapped_column(Integer)         # 1..7 (Пн..Вс)
    para: Mapped[int] = mapped_column(Integer)            # 1..5
    subject: Mapped[str] = mapped_column(String(256))
    teacher: Mapped[str] = mapped_column(String(128), default="")
    # 512, а не 64: в этой колонке у вуза бывает ссылка на онлайн-пару
    # (до 70 символов), и обрезка по 64 давала неработающий огрызок URL.
    room: Mapped[str] = mapped_column(String(512), default="")
    # Номера недель через запятую: "6,8,10,12,14,16". Пусто — пара идёт
    # по чётности. Нужно вузу: там в один слот ставится 2-4 предмета с
    # разными наборами недель.
    weeks: Mapped[str] = mapped_column(String(128), default="",
                                       server_default=text("''"))
    source: Mapped[str] = mapped_column(String(8), default="manual")  # site | manual
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self):
        return f"<BaseLesson {self.group} {self.week_parity}/wd{self.weekday} п{self.para}>"
