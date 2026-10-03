from dataclasses import dataclass

from environs import Env


@dataclass
class TgBot:
    token: str
    admin_ids: list[int]


@dataclass
class Db:
    path: str

    def sqlalchemy_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.path}"


@dataclass
class Config:
    tg_bot: TgBot
    db: Db
    schedule_url: str
    base_url: str
    poll_interval: int
    mode: str  # daily | permanent


def load_config(path: str = ".env") -> Config:
    env = Env()
    env.read_env(path)

    return Config(
        tg_bot=TgBot(
            token=env.str("BOT_TOKEN"),
            admin_ids=env.list("ADMINS", subcast=int),
        ),
        db=Db(path=env.str("SQLITE_PATH", "database.db")),
        schedule_url=env.str(
            "SCHEDULE_URL",
            "https://polaruniversity.ru/obuchayushchimsya/raspisanie-zanyatiy/",
        ),
        base_url=env.str("BASE_URL", "https://polaruniversity.ru"),
        poll_interval=env.int("POLL_INTERVAL", 1800),
        mode=env.str("MODE", "daily"),
    )
