
from sqlalchemy.dialects.postgresql import insert

from infrastructure.database.models import User
from infrastructure.database.repo.base import BaseRepo


class UserRepo(BaseRepo):
    async def get_or_create_user(
            self,
            user_id: int,
            full_name: str,
            language: str,
            username: str | None = None,
    ):
        insert_stmt = (
            insert(User)
            .values(
                id=user_id,
                username=username,
                full_name=full_name,
                language=language,
            )
            .on_conflict_do_update(
                index_elements=[User.id],
                set_={
                    "username": username,
                    "full_name": full_name,
                },
            )
            .returning(User)
        )
        result = await self.session.execute(insert_stmt)

        await self.session.commit()
        return result.scalar_one()
