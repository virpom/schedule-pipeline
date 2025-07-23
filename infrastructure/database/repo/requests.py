from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.repo.lesson import LessonRepo
from infrastructure.database.repo.student_group import StudentGroupRepo
from infrastructure.database.repo.user import UserRepo


@dataclass
class RequestsRepo:
    session: AsyncSession

    @property
    def users(self) -> UserRepo:
        return UserRepo(self.session)

    @property
    def lessons(self) -> LessonRepo:
        return LessonRepo(self.session)

    @property
    def student_group(self) -> StudentGroupRepo:
        return StudentGroupRepo(self.session)
