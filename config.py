import os
from dataclasses import dataclass


def _read_env(path: str) -> None:
    """Подхватить .env, не перетирая уже заданные переменные окружения.

    В докере переменные приходят через --env-file, и файла в контейнере
    может не быть — это не ошибка.
    """
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
    except FileNotFoundError:
        pass


def _ids(name: str) -> list[int]:
    return [int(x) for x in (os.environ.get(name) or "").replace(",", " ").split()]


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
    photos_path: str  # dir with per-weekday photo folders


def load_config(path: str = ".env") -> Config:
    _read_env(path)

    return Config(
        tg_bot=TgBot(
            token=os.environ["BOT_TOKEN"],
            admin_ids=_ids("ADMINS"),
        ),
        db=Db(path=os.environ.get("SQLITE_PATH") or "database.db"),
        schedule_url=os.environ.get("SCHEDULE_URL")
        or "https://eios.norvuz.ru/mod/page/view.php?id=49960",
        photos_path=os.environ.get("PHOTOS_PATH") or "/data/photos",
    )
