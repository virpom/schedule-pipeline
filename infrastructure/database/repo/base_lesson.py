import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert

from common.schedule import PARITY_ANY, teacher_matches
from infrastructure.database.models import BaseLesson
from infrastructure.database.repo.base import BaseRepo


def _fits_week(lesson: BaseLesson, week: int) -> bool:
    """Идёт ли пара на этой неделе.

    ``weeks`` пусто — пара идёт по чётности, её отфильтровал SQL.
    ``weeks`` заполнено — смотрим на список номеров.
    """
    raw = (lesson.weeks or "").strip()
    if not raw:
        return True
    return week in {int(w) for w in raw.split(",") if w.strip().isdigit()}


class BaseLessonRepo(BaseRepo):
    async def get_day(self, group: str, weekday: int, parity: str,
                      week: int | None = None) -> list[BaseLesson]:
        """Пары группы на день недели с учётом чётности.

        Берём строки нужной чётности и ANY (одинаковые каждую неделю);
        при совпадении слота приоритет у конкретной чётности.

        У вуза на один слот бывает несколько пар с разными наборами
        недель (``weeks``). Если передан номер недели — оставляем только
        подходящие; без него возвращаем все, чтобы не потерять пары.
        """
        result = await self.session.execute(
            select(BaseLesson)
            .where(
                BaseLesson.group == group,
                BaseLesson.weekday == weekday,
                BaseLesson.week_parity.in_([parity, PARITY_ANY]),
            )
            .order_by(BaseLesson.para)
        )
        rows = list(result.scalars().all())

        if week is not None:
            rows = [r for r in rows if _fits_week(r, week)]

        specific, any_rows = {}, {}
        for l in rows:
            # Ключ включает weeks: у вуза в одном слоте живут несколько
            # пар, и по одному para их не схлопнуть.
            key = (l.para, l.weeks or "")
            if l.week_parity == PARITY_ANY:
                any_rows[key] = l
            else:
                specific[key] = l
        merged = {**any_rows, **specific}
        return [merged[k] for k in sorted(merged)]

    async def get_week(self, group: str, parity: str,
                       week: int | None = None) -> list[BaseLesson]:
        result = await self.session.execute(
            select(BaseLesson)
            .where(BaseLesson.group == group,
                   BaseLesson.week_parity.in_([parity, PARITY_ANY]))
            .order_by(BaseLesson.weekday, BaseLesson.para)
        )
        rows = list(result.scalars().all())
        if week is not None:
            rows = [r for r in rows if _fits_week(r, week)]
        return rows

    async def upsert(self, group: str, parity: str, weekday: int, para: int,
                     subject: str, teacher: str = "", room: str = "",
                     source: str = "manual", updated_by: int | None = None,
                     weeks: str = "") -> None:
        now = datetime.datetime.now()
        await self.session.execute(
            insert(BaseLesson)
            .values(group=group, week_parity=parity, weekday=weekday, para=para,
                    weeks=weeks, subject=subject, teacher=teacher, room=room,
                    source=source, updated_by=updated_by, updated_at=now)
            .on_conflict_do_update(
                index_elements=["group", "week_parity", "weekday", "para", "weeks"],
                set_=dict(subject=subject, teacher=teacher, room=room,
                          source=source, updated_by=updated_by, updated_at=now),
            )
        )
        await self.session.commit()

    async def delete_slot(self, group: str, parity: str, weekday: int, para: int,
                          weeks: str = "") -> None:
        await self.session.execute(
            delete(BaseLesson).where(
                BaseLesson.group == group,
                BaseLesson.week_parity == parity,
                BaseLesson.weekday == weekday,
                BaseLesson.para == para,
                BaseLesson.weeks == weeks,
            )
        )
        await self.session.commit()

    async def count(self, vuz: bool | None = None) -> int:
        """Число пар, при желании — только вуза или только колледжа."""
        from sqlalchemy import func
        q = select(func.count()).select_from(BaseLesson)
        if vuz is True:
            q = q.where(BaseLesson.group.like("%@vuz"))
        elif vuz is False:
            q = q.where(BaseLesson.group.notlike("%@vuz"))
        result = await self.session.execute(q)
        return result.scalar_one()

    async def get_groups(self) -> list[str]:
        """Группы, у которых есть базовое расписание."""
        result = await self.session.execute(
            select(BaseLesson.group).distinct().order_by(BaseLesson.group)
        )
        return [g for (g,) in result.all()]

    async def get_for_teacher(self, teacher_name: str, weekday: int | None = None,
                              week: int | None = None,
                              parity: str | None = None) -> list[BaseLesson]:
        """Пары преподавателя вуза из базового расписания.

        У вуза нет материализованного слоя на будущее: пары хранятся в
        base_lesson со списком недель. Поэтому расписание преподавателя
        вуза собирается здесь, а не из college_lesson, где вузовских
        пар на произвольную дату может не оказаться.

        ``parity`` — чётность недели (``ODD``/``EVEN``). Вызывающий знает
        её точно: он уже посчитал номер недели вуза. Без фильтра
        преподаватель видел пары чужой недели — те, которых в этот день
        нет ни у одной группы.
        """
        if not (teacher_name or "").strip():
            return []
        surname = teacher_name.split()[0]
        query = (select(BaseLesson)
                 .where(BaseLesson.group.like("%@vuz"),
                        BaseLesson.teacher.like(f"%{surname}%"))
                 .order_by(BaseLesson.weekday, BaseLesson.para))
        if weekday is not None:
            query = query.where(BaseLesson.weekday == weekday)
        if parity is not None:
            query = query.where(
                BaseLesson.week_parity.in_([parity, PARITY_ANY]))
        result = await self.session.execute(query)
        rows = [r for r in result.scalars().all()
                if teacher_matches(r.teacher, teacher_name)]
        if week is not None:
            rows = [r for r in rows if _fits_week(r, week)]
        return rows
