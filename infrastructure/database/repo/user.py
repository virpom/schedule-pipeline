from collections import Counter
from typing import Optional

import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert

from common.schedule import course_group_from_course
from infrastructure.database.models import User
from infrastructure.database.repo.base import BaseRepo


def majority_course_groups(rows) -> dict[str, str]:
    counts: dict[str, Counter] = {}
    for group, course in rows:
        if course is None:
            continue
        counts.setdefault(group, Counter())[course] += 1
    out: dict[str, str] = {}
    for group, counter in counts.items():
        top = counter.most_common()
        if len(top) == 1 or top[0][1] > top[1][1]:
            cg = course_group_from_course(top[0][0])
            if cg:
                out[group] = cg
    return out


class UserRepo(BaseRepo):
    async def get_or_create_user(
            self,
            user_id: int,
            full_name: str,
            language: str,
            username: Optional[str] = None,
    ) -> User:
        insert_stmt = (
            insert(User)
            .values(
                id=user_id,
                username=username,
                full_name=full_name,
                language=language,
                last_seen=datetime.datetime.now(),
                subscribed=True,
                send_image=False,
                bell_mode="off",
                role="student",
            )
            .on_conflict_do_update(
                index_elements=[User.id],
                set_=dict(username=username, full_name=full_name, last_seen=datetime.datetime.now()),
            )
            .returning(User)
        )
        result = await self.session.execute(insert_stmt)
        await self.session.commit()
        return result.scalar_one()

    async def set_role(self, user_id: int, value: str) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(role=value)
        )
        await self.session.commit()

    async def set_group(self, user_id: int, group: str) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(group=group)
        )
        await self.session.commit()

    async def set_teacher_name(self, user_id: int, name: str) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(teacher_name=name)
        )
        await self.session.commit()

    async def set_course(self, user_id: int, course: Optional[int]) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(course=course)
        )
        await self.session.commit()

    async def set_subscribed(self, user_id: int, value: bool) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(subscribed=value)
        )
        await self.session.commit()

    async def set_bell_detail(self, user_id: int, value: str) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(bell_detail=value)
        )
        await self.session.commit()

    async def set_send_image(self, user_id: int, value: bool) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(send_image=value)
        )
        await self.session.commit()

    async def set_bell_mode(self, user_id: int, value: str) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(bell_mode=value)
        )
        await self.session.commit()

    async def get_subscribed(self) -> list[User]:
        result = await self.session.execute(
            select(User).where(
                User.subscribed == True,  # noqa: E712
                (User.group.is_not(None)) | (User.teacher_name.is_not(None)),
            )
        )
        return list(result.scalars().all())

    async def get_bell_subscribers(self) -> list[User]:
        result = await self.session.execute(
            select(User).where(
                User.subscribed == True,  # noqa: E712
                User.bell_mode != "off",
                (User.group.is_not(None)) | (User.teacher_name.is_not(None)),
            )
        )
        return list(result.scalars().all())

    async def get_subscribed_by_group(self, group: str) -> list[User]:
        """Подписчики конкретной группы — для уведомлений о правках старосты."""
        result = await self.session.execute(
            select(User).where(
                User.subscribed == True,  # noqa: E712
                User.group == group,
            )
        )
        return list(result.scalars().all())

    async def get(self, user_id: int) -> Optional[User]:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def find_by_username(self, username: str) -> list[User]:
        """Найти пользователя по @нику (регистр и ведущий @ не важны)."""
        clean = username.lstrip("@").strip()
        if not clean:
            return []
        result = await self.session.execute(
            select(User).where(func.lower(User.username) == clean.lower())
        )
        return list(result.scalars().all())

    async def search(self, query: str, limit: int = 8) -> list[User]:
        """Поиск по @нику, имени или id — для выдачи прав редактора."""
        q = query.strip()
        if not q:
            return []
        if q.isdigit():
            user = await self.get(int(q))
            return [user] if user else []

        clean = q.lstrip("@").lower()
        result = await self.session.execute(
            select(User)
            .where(
                (func.lower(User.username) == clean)
                | (func.lower(User.username).like(f"%{clean}%"))
                | (func.lower(User.full_name).like(f"%{clean}%"))
            )
            .order_by(User.last_seen.desc().nullslast())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_all(self) -> list[User]:
        result = await self.session.execute(select(User))
        return list(result.scalars().all())

    async def get_by_group(self, group: Optional[str]) -> list[User]:
        cond = User.group.is_(None) if group is None else (User.group == group)
        result = await self.session.execute(select(User).where(cond).order_by(User.created_at))
        return list(result.scalars().all())

    async def get_teachers_users(self) -> list[User]:
        result = await self.session.execute(
            select(User).where(User.role == "teacher", User.teacher_name.is_not(None))
        )
        return list(result.scalars().all())

    async def get_group_course_map(self) -> dict[str, str]:
        result = await self.session.execute(
            select(User.group, User.course).where(
                User.group.is_not(None), User.course.is_not(None)
            )
        )
        return majority_course_groups(result.all())
