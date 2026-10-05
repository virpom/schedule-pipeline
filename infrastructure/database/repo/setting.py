from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from infrastructure.database.models import Setting
from infrastructure.database.repo.base import BaseRepo


DEFAULTS = {
    "poll_interval": "300",
    "notify_rate": "20",
    "night_start": "23:00",
    "night_end": "07:00",
    "deadline_hour": "20",
    "support_link": "",
}


class SettingRepo(BaseRepo):
    async def get_all(self) -> dict[str, str]:
        result = await self.session.execute(select(Setting))
        stored = {s.key: s.value for s in result.scalars().all()}
        return {**DEFAULTS, **stored}

    async def set(self, key: str, value: str) -> None:
        await self.session.execute(
            insert(Setting)
            .values(key=key, value=value)
            .on_conflict_do_update(index_elements=["key"], set_=dict(value=value))
        )
        await self.session.commit()
