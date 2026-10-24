"""Справочник групп вуза — для навигации при выборе."""
from sqlalchemy import select

from infrastructure.database.models import VuzGroup
from infrastructure.database.repo.base import BaseRepo


class VuzGroupRepo(BaseRepo):
    async def all(self) -> list[VuzGroup]:
        result = await self.session.execute(
            select(VuzGroup).order_by(VuzGroup.faculty, VuzGroup.course, VuzGroup.name)
        )
        return list(result.scalars().all())

    async def get(self, name: str) -> VuzGroup | None:
        return await self.session.get(VuzGroup, name)

    async def forms(self) -> list[str]:
        """Формы обучения, по которым вообще есть группы."""
        result = await self.session.execute(
            select(VuzGroup.form).distinct().order_by(VuzGroup.form)
        )
        return [f for (f,) in result.all()]

    async def courses(self, faculty: str, form: str) -> list[int]:
        """Курсы внутри факультета и формы — только те, где есть группы."""
        result = await self.session.execute(
            select(VuzGroup.course)
            .where(VuzGroup.faculty == faculty, VuzGroup.form == form)
            .distinct()
            .order_by(VuzGroup.course)
        )
        return [c for (c,) in result.all()]

    async def by_course(self, faculty: str, form: str, course: int) -> list[str]:
        result = await self.session.execute(
            select(VuzGroup.name)
            .where(VuzGroup.faculty == faculty,
                   VuzGroup.form == form,
                   VuzGroup.course == course)
            .order_by(VuzGroup.name)
        )
        return [n for (n,) in result.all()]
