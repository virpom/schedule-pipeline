from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select, delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.models import Lesson, StudentGroup, Stream
from infrastructure.database.repo.base import BaseRepo
from parsers.data_processor import LessonInfo, StreamInfo


class LessonRepo(BaseRepo):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def add_lesson(
            self,
            lesson: LessonInfo,
            stream_id: int,
    ) -> int:
        insert_stmt = (
            insert(Lesson)
            .values(
                session_type=lesson.session_type,
                title=lesson.title,
                start_time=lesson.start_time,
                end_time=lesson.end_time,
                group_code=lesson.group_code,
                stream_id=stream_id,
            )
            .on_conflict_do_nothing(
                index_elements=["title", "start_time", "group_code", "stream_id"]
            )
            .returning(Lesson.id)
        )

        result = await self.session.execute(insert_stmt)
        return result.scalar_one()

    async def bulk_add_lessons(self, lessons: list[LessonInfo], stream_id: int) -> list[int]:
        if not lessons:
            return []

        insert_stmt = (
            insert(Lesson)
            .values(
                [
                    {
                        "session_type": lesson.session_type,
                        "title": lesson.title[:128] if len(lesson.title) > 128 else lesson.title,
                        "start_time": lesson.start_time,
                        "end_time": lesson.end_time,
                        "group_code": lesson.group_code,
                        "stream_id": stream_id,
                    }
                    for lesson in lessons
                ]
            )
            .on_conflict_do_nothing(
                index_elements=["title", "start_time", "group_code", "stream_id"]
            )
            .returning(Lesson.id)
        )

        result = await self.session.execute(insert_stmt)
        return list(result.scalars().all())

    async def delete_all(self) -> None:
        await self.session.execute(delete(Lesson))

    async def get_classes_by_time(self, group_code: str, start: datetime, end: datetime):
        subquery = select(StudentGroup.stream_id).where(StudentGroup.code == group_code).scalar_subquery()

        result = await self.session.execute(
            select(Lesson)
            .where(
                and_(
                    or_(
                        Lesson.group_code == group_code,
                        and_(
                            Lesson.group_code == str(0),
                            Lesson.stream_id == subquery
                        )
                    ),
                    Lesson.start_time >= start,
                    Lesson.end_time <= end
                )
            )
            .order_by(Lesson.start_time)
        )
        return result.scalars().all()

    async def get_classes_for_current_week(self, group_code: str):
        today = datetime.now().date()
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        return await self.get_classes_by_time(group_code, start_of_week, end_of_week)

    async def get_or_create_stream_id(
            self, stream: StreamInfo
    ) -> int:
        insert_stmt = (
            insert(Stream)
            .values(
                code=stream.code,
                course=stream.course,
                specialization_code=stream.specialization_code,
                specialization_title=stream.specialization_title,
            )
            .on_conflict_do_update(
                index_elements=["code", "course", "specialization_code"],
                set_={"specialization_title": stream.specialization_title},
            )
            .returning(Stream.id)
        )

        result = await self.session.execute(insert_stmt)
        return result.scalar_one()
