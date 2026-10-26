"""Сломанная структура файла доходит до тревоги, а сеть — нет.

План 071. `sync_once` оборачивает каждый файл в `_step`, и `except
Exception` глотал `EiosParseError` наравне с сетевыми сбоями. В
результате главный сценарий — «сайт жив, но файл другой» — тревоги не
поднимал вовсе: админ видел только «сайт не отвечает», а бот молча
работал на старых данных.

Второй дефект: сетевой сбой снимал тревогу о структуре с текстом
«Файлы снова разбираются», хотя ничего не разбиралось. На мигающем
сайте это давало «проблема → восстановилось → проблема» каждый цикл.
"""
import inspect

from tgbot.services import poller, sync_eios


def test_parse_error_is_tracked_separately():
    """`_step` отличает ошибку разбора от сетевой.

    Иначе поллер не может решить, стоит ли будить человека: сеть
    восстановится сама, сломанная структура — нет.
    """
    src = inspect.getsource(sync_eios.sync_once)
    assert "except eios.EiosParseError" in src, (
        "parse-ошибка не отделена от общей — план 071"
    )
    assert "parse_failed.append" in src
    assert 'changed["parse_failed"]' in src


def test_failed_list_format_unchanged():
    """Формат `failed` остаётся list[str].

    Его читают три места в poller.py, и они проверяют непустоту и печатают
    имена. Переход на кортежи (name, kind) напечатал бы кортежи в лог.
    """
    src = inspect.getsource(sync_eios.sync_once)
    assert "failed: list[str] = []" in src
    assert 'changed["failed"] = failed' in src
    assert "parse_failed: list[str] = []" in src


def test_network_failure_does_not_clear_structure_alert():
    """Сетевой сбой не должен снимать тревогу о структуре.

    Раньше в ветке else стоял clear с «Файлы снова разбираются» —
    ложное восстановление при мигающем сайте.
    """
    src = inspect.getsource(poller._report_failure)
    # В ветке сети не должно быть clear со структ��рой.
    assert 'alerts.clear(bot, repo, config, "structure"' not in src, (
        "сетевой сбой всё ещё снимает тревогу о структуре"
    )


def test_structure_alert_has_own_reporter():
    """Тревога о разборе — отдельная функция со своим текстом."""
    src = inspect.getsource(poller._report_parse_failure)
    assert '"structure"' in src
    assert "не разбираются" in src


def test_clear_happens_only_on_full_success():
    """Снимаем тревогу только когда разбор прошёл на всех файлах.

    Условие `elif not failed` — то есть ни один файл не упал, ни по
    сети, ни по разбору.
    """
    src = inspect.getsource(poller.poll_once)
    i_parse = src.index("if parse_failed:")
    i_clear = src.index('alerts.clear(bot, repo, config, "structure"')
    assert i_parse < i_clear, "clear стоит раньше проверки parse_failed"
    # Между ними должно быть ветвление, а не безусловный clear.
    between = src[i_parse:i_clear]
    assert "elif not failed:" in between, between


def test_parse_failure_key_is_separate_from_partial():
    """Два разных ключа: иначе тревоги глушат друг друга по хешу.

    `alerts.alert` дедуплицирует по тексту и хранит его в setting — при
    общем ключе вторая тревога не отправилась бы.
    """
    parse_src = inspect.getsource(poller._report_parse_failure)
    partial_src = inspect.getsource(poller._report_partial_failure)
    assert '"structure"' in parse_src
    assert '"partial"' in partial_src
