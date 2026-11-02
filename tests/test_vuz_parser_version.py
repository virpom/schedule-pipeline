"""Правка парсера вуза сбрасывает кеш разбора.

Синк вуза пропускает разбор, если хеш файла не изменился. Хеш считался
по одним байтам, поэтому исправление парсера до базы не доходило:
файл тот же, хеш совпал. 03.11.2026 так и вышло — четверг у АП-23
разбирался правильно, а в базе оставался пустым.

Это уже второй такой случай: у колледжа то же самое было с
_sync_ochoe (PARSER_VERSION в sync_eios.py).
"""
import hashlib

import tgbot.services.sync_vuz as sync


def test_version_participates_in_hash():
    data = b"<xls bytes>"
    assert sync._sha(data) != hashlib.sha256(data).hexdigest(), (
        "хеш равен чистому sha256 — версия парсера не учтена")


def test_version_change_changes_hash(monkeypatch):
    data = b"<xls bytes>"
    before = sync._sha(data)
    monkeypatch.setattr(sync, "PARSER_VERSION", "999")
    assert sync._sha(data) != before


def test_version_is_declared():
    assert sync.PARSER_VERSION.strip()
