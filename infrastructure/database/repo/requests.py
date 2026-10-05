from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.repo.bell_reminder import BellReminderRepo
from infrastructure.database.repo.bell_schedule import BellScheduleRepo
from infrastructure.database.repo.chat import ChatRepo
from infrastructure.database.repo.college_lesson import CollegeLessonRepo
from infrastructure.database.repo.schedule_file import ScheduleFileRepo
from infrastructure.database.repo.setting import SettingRepo
from infrastructure.database.repo.user import UserRepo


@dataclass
class RequestsRepo:
    session: AsyncSession

    @property
    def users(self) -> UserRepo:
        return UserRepo(self.session)

    @property
    def chats(self) -> ChatRepo:
        return ChatRepo(self.session)

    @property
    def college_lessons(self) -> CollegeLessonRepo:
        return CollegeLessonRepo(self.session)

    @property
    def bell_schedule(self) -> BellScheduleRepo:
        return BellScheduleRepo(self.session)

    @property
    def schedule_files(self) -> ScheduleFileRepo:
        return ScheduleFileRepo(self.session)

    @property
    def settings(self) -> SettingRepo:
        return SettingRepo(self.session)

    @property
    def reminders(self) -> BellReminderRepo:
        return BellReminderRepo(self.session)
