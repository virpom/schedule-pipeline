import datetime
import os
import random

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_EXT = (".jpg", ".jpeg", ".png")


def weekday_folder(date: datetime.date) -> str:
    return WEEKDAYS[date.weekday()]


def list_photos(photos_path: str, weekday: str) -> list[str]:
    d = os.path.join(photos_path, weekday)
    if not os.path.isdir(d):
        return []
    return [
        os.path.join(d, f)
        for f in sorted(os.listdir(d))
        if f.lower().endswith(_EXT)
    ]


def random_photo(photos_path: str, weekday: str) -> str | None:
    photos = list_photos(photos_path, weekday)
    return random.choice(photos) if photos else None
