from notion_reader import Card
from sync import keep_labeled, too_many_unlabeled


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
