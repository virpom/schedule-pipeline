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
    poll_interval: int  # стартовое значение; дальше живёт в БД (команда /setpoll)
    notify_rate: float  # messages per second for broadcasts
    photos_path: str  # dir with per-weekday photo folders


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
            "https://eios.norvuz.ru/mod/page/view.php?id=49960",
        ),
        base_url=env.str("BASE_URL", "https://norvuz.ru"),
        poll_interval=env.int("POLL_INTERVAL", 300),
        notify_rate=env.float("NOTIFY_RATE", 20.0),
        photos_path=env.str("PHOTOS_PATH", "/data/photos"),
    )
