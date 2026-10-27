"""Прошедшие замены не копятся в substitution (план 055 / ранг 69).

Раньше прошедшие даты отсекал `get_dates(since=today)` при сборке
рассылки. Когда рассылку перевели на отпечатки дат в college_lesson,
`get_dates` стал мёртвым — и отсекать перестало что-либо: на проде
27.10 в таблице лежало 201 строка из 256.

Сначала план 055 считал проблемой «рассылка идёт по всем 15 датам
замен». Проверил поллер: это уже не так, рассылка идёт по сравнении
отпечатков `digest_by_date` и будит только группы с изменениями. Так
что чинить нужно было не рассылку, а накопление строк.
"""
import inspect

from tgbot.services import poller


def test_delete_before_exists():
    from infrastructure.database.repo.substitution import SubstitutionRepo
    assert hasattr(SubstitutionRepo, "delete_before")


def test_delete_before_is_strict_enough():
    """Храним с запасом в день: редактор показывает «вчера..+6»."""
    from infrastructure.database.repo.substitution import SubstitutionRepo
    src = inspect.getsource(SubstitutionRepo.delete_before)
    assert "Substitution.date < date" in src


def test_poller_purges_substitutions():
    src = inspect.getsource(poller._purge_past)
    assert "substitutions.delete_before" in src, "замены не чистятся"


def test_purge_keeps_yesterday():
    """Вчерашние замены нужны редактору."""
    src = inspect.getsource(poller._purge_past)
    assert "days=1" in src, "чистится вчерашний день"


def test_past_not_written():
    """На границе записи прошедшие тоже отсекаются, а не только чистятся."""
    from tgbot.services import sync_eios
    src = inspect.getsource(sync_eios.replace_substitutions)
    assert "if sub.date < today:" in src, "прошедшие замены пишутся в слой"


def test_get_dates_removed():
    """Мёртвый метод убран — нечего путать с рабочим путём."""
    from infrastructure.database.repo.substitution import SubstitutionRepo
    assert not hasattr(SubstitutionRepo, "get_dates")
