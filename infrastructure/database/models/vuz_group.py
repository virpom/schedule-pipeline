from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class VuzGroup(Base):
    """Справочник групп вуза: факультет, курс, форма обучения.

    Нужен только для навигации при выборе группы. По имени группы
    (``ЭК-26-1``) факультет не определить — он берётся из листа файла
    расписания, поэтому и приходится хранить отдельно.

    Имя хранится с суффиксом ``@vuz``: группы вуза и колледжа живут в
    одних таблицах, и ``ЭК-23`` у них — разные люди.
    """

    __tablename__ = "vuz_group"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    faculty: Mapped[str] = mapped_column(String(16), index=True)
    course: Mapped[int] = mapped_column(Integer)
    form: Mapped[str] = mapped_column(String(16))   # full | part | extramural

    def __repr__(self):
        return f"<VuzGroup {self.name} {self.faculty}/{self.course}/{self.form}>"
