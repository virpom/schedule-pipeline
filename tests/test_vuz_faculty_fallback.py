"""Новый факультет вуза не получает пустой код (план 157).

_faculty знал ровно два корня названия и для остальных возвращал ("", "").
Пустой код доезжал до кнопки: FACULTY_NAMES.get("", "") = "", а Telegram
на пустой подписи удаляет весь ряд клавиатуры — без ошибки, без записи в
лог. Студент видел «группы пропали».

Сейчас неизвестный факультет получает код из текста шапки.
"""
from parsers.vuz import _faculty_fallback


class _Sheet:
    """Минимальный двойник Sheet: сетка строк и текст."""

    def __init__(self, rows):
        self.rows = rows
        self.nrows = len(rows)
        self.ncols = max(len(r) for r in rows)

    def text(self, r, c):
        row = self.rows[r]
        return row[c] if c < len(row) else ""


def test_known_faculties_untouched():
    from parsers import vuz
    r = vuz.parse(open("tests/fixtures/1-ochnoe.xls", "rb").read())
    codes = {g.faculty for g in r.groups}
    assert codes == {"GTF", "FEU"}, codes


def test_unknown_faculty_gets_code():
    sheet = _Sheet([["МИНЕРАЛЬНО-СЫРЬЕВОЙ ФАКУЛЬТЕТ"], [""]])
    code, name = _faculty_fallback(sheet)
    assert code, "пустой код снова"
    assert code != ""
    assert "МИНЕРАЛЬНО" in name.upper() or "ФАКУЛЬТЕТ" in name.upper()


def test_no_header_gives_nonempty():
    sheet = _Sheet([["x"], [""]])
    code, name = _faculty_fallback(sheet)
    assert code == "OTH" and name == "Другой"


def test_faculty_code_is_safe_for_callback():
    """Код едет в callback_data (лимит 64 байта) — без мусора."""
    sheet = _Sheet([["ФАКУЛЬТЕТ " + "ОченьДлинноеСловоНазвания " * 5]])
    code, _ = _faculty_fallback(sheet)
    assert len(code) <= 6, code
    assert code.isalnum() or code == "OTH"
