import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert

from infrastructure.database.models import Substitution
from infrastructure.database.repo.base import BaseRepo


class SubstitutionRepo(BaseRepo):
    async def count(self, vuz: bool | None = None) -> int:
        """Число замен, при желании — только вуза или только колледжа."""
        from sqlalchemy import func
        q = select(func.count()).select_from(Substitution)
        if vuz is True:
            q = q.where(Substitution.group.like("%@vuz"))
        elif vuz is False:
            q = q.where(Substitution.group.notlike("%@vuz"))
        result = await self.session.execute(q)
        return result.scalar_one()

    async def delete_before(self, date: datetime.date) -> int:
        """Убрать замены за дни до указанного.

        Раньше прошедшие отсекал get_dates(since=today) при сборке
        рассылки; после перехода на отпечатки дат их перестал отсекать
        кто-либо, и в таблице лежало 201 из 256 строк. Редактор
        показывает «вчера..+6», поэтому храним с запасом в один день.
        """
        result = await self.session.execute(
            delete(Substitution).where(Substitution.date < date)
        )
        await self.session.commit()
        return result.rowcount or 0

    async def get_for_date(self, group: str, date: datetime.date) -> list[Substitution]:
        result = await self.session.execute(
            select(Substitution)
            .where(Substitution.group == group, Substitution.date == date)
            .order_by(Substitution.para)
        )
        return list(result.scalars().all())

    async def set(self, date: datetime.date, group: str, para: int, action: str,
                  subject: str = "", teacher: str = "", room: str = "",
                  comment: str = "", source: str = "manual",
                  created_by: int | None = None) -> None:
        now = datetime.datetime.now()
        await self.session.execute(
            insert(Substitution)
            .values(date=date, group=group, para=para, action=action,
                    subject=subject, teacher=teacher, room=room, comment=comment,
                    source=source, created_by=created_by, created_at=now)
            .on_conflict_do_update(
                index_elements=["date", "group", "para"],
                set_=dict(action=action, subject=subject, teacher=teacher,
                          room=room, comment=comment, source=source,
                          created_by=created_by, created_at=now),
            )
        )
        await self.session.commit()

    async def delete(self, date: datetime.date, group: str, para: int) -> None:
        await self.session.execute(
            delete(Substitution).where(
                Substitution.date == date, Substitution.group == group,
                Substitution.para == para,
            )
        )
        await self.session.commit()

