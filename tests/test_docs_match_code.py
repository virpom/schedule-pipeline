"""Документация не врёт про проверяемые вещи.

Ранг 20. Документы отстали от кода: «69 тестов» при 510 реальных,
«не реализовано» про вуз при 1253 строках парсера и синхронизации,
две миграции вместо одиннадцати, `python tests/test_parser.py` —
файла нет.

Эти проверки ловят расхождения, которые видно без запуска бота:
счётчик тестов, список миграций и ссылки на несуществующие файлы.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _test_files() -> list[pathlib.Path]:
    return sorted((ROOT / "tests").glob("test_*.py"))


def _migrations() -> list[str]:
    return sorted(p.stem for p in (ROOT / "migrations" / "versions").glob("*.py")
                  if not p.name.startswith("__"))


def test_readme_test_count_is_plausible():
    """Число в README не должно отставать на порядок.

    Точное совпадение не проверяем: pytest раскрывает параметризацию, и
    счётчик разъезжается на единицы при каждом новом тесте — такой тест
    краснел бы вечно. Ловим именно «69 при 510».
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    claimed = [int(n) for n in re.findall(r"(\d+) тестов", readme)]
    assert claimed, "README не называет число тестов"
    files = len(_test_files())
    for n in claimed:
        assert files * 0.6 <= n <= files * 8, \
            f"README: {n} тестов при {files} файлах тестов"


def test_roadmap_test_count_is_plausible():
    doc = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    m = re.search(r"Всего тестов: \*\*(\d+)\*\*", doc)
    assert m, "ROADMAP не называет число тестов"
    files = len(_test_files())
    assert files * 0.6 <= int(m.group(1)) <= files * 8, \
        f"ROADMAP: {m.group(1)} тестов при {files} файлах"


def test_architecture_lists_real_head():
    doc = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    line = next(l for l in doc.splitlines() if l.startswith("Миграции:"))
    migs = _migrations()
    assert migs[-1] in line, f"head {migs[-1]} не указан: {line}"
    for name in re.findall(r"`(\d{4}_[a-z_]+)`", line):
        assert name in migs, f"нет миграции {name}"


def test_no_reference_to_missing_test_files():
    """Документы не отправляют запускать то, чего нет."""
    for doc in (ROOT / "docs").glob("*.md"):
        text = doc.read_text(encoding="utf-8")
        for ref in re.findall(r"tests/(test_[a-z_]+\.py)", text):
            assert (ROOT / "tests" / ref).exists(), \
                f"{doc.name} ссылается на tests/{ref}, которого нет"


def test_vuz_not_called_unimplemented():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for line in readme.splitlines():
        if "VUZ.md" in line:
            assert "не реализовано" not in line, f"README врёт про вуз: {line}"


def test_vuz_parser_actually_exists():
    """Предпосылка: вуз реализован, иначе тест выше бессмыслен."""
    assert (ROOT / "parsers" / "vuz.py").exists()
    assert (ROOT / "tgbot" / "services" / "sync_vuz.py").exists()
