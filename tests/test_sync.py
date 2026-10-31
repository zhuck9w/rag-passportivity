import pytest

import sync
from notion_reader import Card
from sync import keep_labeled, split_gone, too_many_gone, too_many_unlabeled


def _card(country: str) -> Card:
    return Card(page_id=country or "blank", program="P", country=country,
                status="Actual", owners="", url="", last_edited="2026-01-01T00:00:00.000Z")


def test_keep_labeled_drops_countryless():
    cards, skipped = keep_labeled([_card("Greece"), _card(""), _card("Malta")])
    assert [c.country for c in cards] == ["Greece", "Malta"]
    assert skipped == 1


def test_keep_labeled_all_labeled():
    cards, skipped = keep_labeled([_card("Greece")])
    assert len(cards) == 1 and skipped == 0


def test_too_many_unlabeled_thresholds():
    # порог = max(5, четверть карточек); достижение порога = стоп
    assert too_many_unlabeled(47, 1) is False   # одна разлейбленная — норма
    assert too_many_unlabeled(47, 10) is False  # ниже порога max(5, 11)
    assert too_many_unlabeled(47, 11) is True   # четверть базы — подозрительно, стоп
    assert too_many_unlabeled(8, 4) is False    # ниже минимального порога 5
    assert too_many_unlabeled(8, 5) is True     # маленькая база: 5 из 8 — стоп


def test_too_many_gone_thresholds():
    # порог — размер самой маленькой базы Notion (3 карточки): её пропажа
    # целиком должна ловиться, одиночные удаления — проходить
    assert too_many_gone(0) is False
    assert too_many_gone(1) is False
    assert too_many_gone(2) is False
    assert too_many_gone(3) is True
    assert too_many_gone(21) is True


def test_split_gone_holds_vanished_but_not_unlabeled():
    gone = ["a", "b", "c", "u1", "u2"]
    assert split_gone(gone, {"u1", "u2"}, False) == (["u1", "u2"], ["a", "b", "c"])
    assert split_gone(gone, {"u1", "u2"}, True) == (gone, [])          # --allow-mass-delete
    assert split_gone(["a", "b", "u1"], {"u1"}, False) == (["a", "b", "u1"], [])  # 2 пропавших — норма
    # снятие лейблов с 3 страниц — штатный вывод из бота, не «потерянная база»
    assert split_gone(["u1", "u2", "u3"], {"u1", "u2", "u3"}, False) == (["u1", "u2", "u3"], [])


def _fake_sync(monkeypatch, raw_cards, known):
    """sync.run без сети: Notion и БД подменены, изменённых страниц нет.
    → списки, куда попадут удалённые page_id и записи sync_log."""
    deleted, logged = [], []
    monkeypatch.setattr(sync.config, "require", lambda *names: None)
    monkeypatch.setattr(sync.nr, "list_cards", lambda: raw_cards)
    monkeypatch.setattr(sync.db, "get_sync_state", lambda: dict(known))
    monkeypatch.setattr(sync.db, "delete_pages", lambda ids: deleted.extend(ids))
    monkeypatch.setattr(sync.db, "log_sync", lambda **kw: logged.append(kw))
    return deleted, logged


def _live_and_known():
    live = [_card("Greece"), _card("Malta")]
    known = {c.page_id: c.last_edited for c in live}
    known.update({"x1": "t", "x2": "t", "x3": "t"})  # целая база пропала из обхода
    return live, known


def test_run_holds_mass_vanish_and_signals(monkeypatch):
    deleted, logged = _fake_sync(monkeypatch, *_live_and_known())
    with pytest.raises(SystemExit, match="ОТЛОЖЕНО"):
        sync.run(full=False, dry=False)
    assert deleted == []                                   # ничего не удалено
    assert "ОТЛОЖЕНО удаление страниц: 3" in logged[0]["programs"]
    assert logged[0]["deleted"] == 0


def test_run_allow_mass_delete_deletes(monkeypatch):
    deleted, logged = _fake_sync(monkeypatch, *_live_and_known())
    sync.run(full=False, dry=False, allow_mass_delete=True)
    assert deleted == ["x1", "x2", "x3"]


def test_run_unlabeled_pages_deleted_without_guard(monkeypatch):
    live = [_card("Greece"), _card("Malta")]
    unlabeled = [Card(page_id=f"u{i}", program="P", country="", status="", owners="",
                      url="", last_edited="t") for i in range(3)]
    known = {c.page_id: c.last_edited for c in live + unlabeled}
    deleted, logged = _fake_sync(monkeypatch, live + unlabeled, known)
    sync.run(full=False, dry=False)  # снятие лейбла — штатно, без SystemExit
    assert deleted == ["u0", "u1", "u2"]
