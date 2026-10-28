"""Правка парсера сбрасывает кеш разбора.

`_sync_ochoe` пропускает разбор, если хеш файла не изменился. Но хеш
считался только по байтам файла: поправили парсер — файл на сайте тот
же, хеш совпал, база осталась со старыми данными.

Так и вышло 28.10.2026: шестая пара колледжа разбиралась правильно (711
пар на фикстуре), а на проде в base_lesson оставалось 704 — синк молча
пропускал разбор. Пришлось запускать перезапись руками.
"""
import tgbot.services.sync_eios as sync


def test_version_participates_in_hash():
    same = b"<xlsx bytes>"
    assert sync._sha(same) == sync._sha(same), "хеш нестабилен"
    # Хеш не должен быть чистым sha256 файла — иначе версия не учтена.
    import hashlib
    assert sync._sha(same) != hashlib.sha256(same).hexdigest()


def test_versions_differ_give_different_hash(monkeypatch):
    data = b"<xlsx bytes>"
    before = sync._sha(data)
    monkeypatch.setattr(sync, "PARSER_VERSION", "999")
    assert sync._sha(data) != before


def test_version_is_declared():
    assert sync.PARSER_VERSION.strip()
