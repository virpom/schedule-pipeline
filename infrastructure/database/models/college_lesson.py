import datetime

from sqlalchemy import Boolean, Date, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TableNameMixin


class CollegeLesson(Base, TableNameMixin):
    """Пары, скачанные с сайта (режим «временного» расписания).

    Остаётся как архив данных, собранных парсером до перехода на модель
    BaseLesson + Substitution. Поле source отличает их от ручных правок.
    """

    # В боевой БД этот индекс есть (создан до перехода на слои). Держим его
    # и в модели: иначе тесты на in-memory SQLite не воспроизводят главное
    # ограничение — одну пару на (дата, группа, номер). Из-за этого
    # наложение двух пар вуза роняло материализацию только на проде.
    __table_args__ = (
        UniqueConstraint("date", "group", "para", name="uc_college_lesson"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime.date] = mapped_column(Date, index=True)
    group: Mapped[str] = mapped_column(String(32), index=True)
    para: Mapped[int] = mapped_column(Integer)
    para_end: Mapped[int] = mapped_column(Integer)
    subject: Mapped[str] = mapped_column(String(256))
    teacher: Mapped[str] = mapped_column(String(128), default="")
    # 512, а не 64: у вуза здесь бывает ссылка на онлайн-пару.
    room: Mapped[str] = mapped_column(String(512), default="")
    # Время пары из самой ячейки («с 18.00 до 21.00», «5-я пара»). Пять
    # пар колледжа идут не по звонку: без этого студент видел время
    # обычной пары и приходил на два часа раньше.
    time_note: Mapped[str] = mapped_column(String(64), default="")
    source_url: Mapped[str] = mapped_column(String(512), default="")
    source: Mapped[str] = mapped_column(String(8), server_default=text("'site'"))
    # Пара пришла из листка замен. Нужен, чтобы пометить её значком в
    # расписании: студент должен видеть, что это не по постоянному плану.
    changed: Mapped[bool] = mapped_column(Boolean, default=False,
                                          server_default=text("0"))
    # "cancel" — пара отменена. Пусто — обычная пара или замена.
    # Без этого отмена рисовалась значком замены: отличить их было нечем.
    action: Mapped[str] = mapped_column(String(8), default="",
                                        server_default=text("''"))

    def __repr__(self):
        return f"<CollegeLesson {self.date} {self.group} п{self.para} {self.subject}>"
