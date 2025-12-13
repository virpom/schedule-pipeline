from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepo:
    def __init__(self, session) -> None:
        self.session: AsyncSession = session
