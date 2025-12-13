from sqlalchemy.dialects.postgresql import insert

from infrastructure.database.models import StudentGroup
from infrastructure.database.repo.base import BaseRepo


class StudentGroupRepo(BaseRepo):
    async def get_or_create_group(self, code: str, stream_id: int) -> str:
        insert_stmt = (
            insert(StudentGroup)
            .values(
                code=code,
                stream_id=stream_id
            )
            .on_conflict_do_update(
                index_elements=["code"],
                set_={"stream_id": stream_id},
            ).returning(StudentGroup.code)
        )
        result = await self.session.execute(insert_stmt)

        await self.session.commit()
        return result.scalar_one()
