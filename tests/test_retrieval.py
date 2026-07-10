from retrieval import _pick_survey, _with_anchors, parse_rewrite


def test_with_anchors_dedup_and_prepend():
    frags = [{"id": 1, "content": "a"}, {"id": 2, "content": "b"}]
    anchors = [{"id": 2, "content": "дубль"}, {"id": 3, "content": "интро"}]
    merged = _with_anchors(frags, anchors)
    assert [f["id"] for f in merged] == [3, 1, 2]  # якорь впереди, без дублей

COUNTRIES = ["Мальта", "Португалия"]


def test_parse_ok_and_country_case_insensitive():
    raw = ('Вот JSON: {"query": "порог инвестиций Мальта", "countries": ["мальта"], '
           '"topic": "инвестиции и стоимость"}')
    q, matched, unknown, topic, survey = parse_rewrite(raw, "исходный", COUNTRIES)
    assert q == "порог инвестиций Мальта"
    assert matched == ["Мальта"] and unknown == []
    assert topic == "инвестиции и стоимость"


def test_parse_two_countries():
    raw = '{"query": "сравнение порогов", "countries": ["Мальта", "Португалия"]}'
    q, matched, unknown, topic, survey = parse_rewrite(raw, "и", COUNTRIES)
    assert matched == ["Мальта", "Португалия"] and unknown == []


def test_parse_empty_countries():
    q, matched, unknown, topic, survey = parse_rewrite(
        '{"query": "все программы", "countries": []}', "и", COUNTRIES)
    assert matched == [] and unknown == []


def test_parse_garbage_falls_back():
    q, matched, unknown, topic, survey = parse_rewrite(
        "не смогу помочь", "исходный вопрос", COUNTRIES)
    assert (q, matched, unknown, topic, survey) == ("исходный вопрос", [], [], "другое", False)


def test_parse_unknown_country_reported():
    q, matched, unknown, topic, survey = parse_rewrite(
        '{"query": "q", "countries": ["Атлантида"]}', "и", COUNTRIES)
    assert matched == [] and unknown == ["Атлантида"]


def test_parse_valid_topic():
    q, matched, unknown, topic, survey = parse_rewrite(
        '{"query": "q", "countries": [], "topic": "налоги"}', "и", COUNTRIES)
    assert topic == "налоги"


def test_parse_invalid_topic_becomes_other():
    q, matched, unknown, topic, survey = parse_rewrite(
        '{"query": "q", "countries": [], "topic": "погода на Марсе"}', "и", COUNTRIES)
    assert topic == "другое"


def test_parse_missing_topic_becomes_other():
    q, matched, unknown, topic, survey = parse_rewrite(
        '{"query": "q", "countries": []}', "и", COUNTRIES)
    assert topic == "другое"


def test_parse_survey_true():
    q, matched, unknown, topic, survey = parse_rewrite(
        '{"query": "программы ВНЖ в ЕС", "countries": [], "survey": true}', "и", COUNTRIES)
    assert survey is True


def test_parse_survey_false():
    q, matched, unknown, topic, survey = parse_rewrite(
        '{"query": "q", "countries": [], "survey": false}', "и", COUNTRIES)
    assert survey is False


def test_parse_survey_missing_defaults_false():
    q, matched, unknown, topic, survey = parse_rewrite(
        '{"query": "q", "countries": []}', "и", COUNTRIES)
    assert survey is False


def test_parse_survey_garbage_defaults_false():
    for junk in ("null", "0", '""', "[]"):
        q, matched, unknown, topic, survey = parse_rewrite(
            '{"query": "q", "countries": [], "survey": %s}' % junk, "и", COUNTRIES)
        assert survey is False, junk


# --- _pick_survey: чистая логика обзорного режима ---

def _hit(country, sim):
    return {"country": country, "similarity": sim, "content": f"{country} {sim}"}


def test_pick_survey_filters_below_soft_threshold():
    hits = [_hit("Мальта", 0.50), _hit("Кипр", 0.44), _hit("Греция", 0.449)]
    picked, countries = _pick_survey(hits)
    assert [h["country"] for h in picked] == ["Мальта"]
    assert countries == ["Мальта"]


def test_pick_survey_sorts_by_similarity_desc():
    hits = [_hit("Кипр", 0.47), _hit("Мальта", 0.52), _hit("Греция", 0.49)]
    picked, countries = _pick_survey(hits)
    assert [h["similarity"] for h in picked] == [0.52, 0.49, 0.47]


def test_pick_survey_caps_at_max_fragments():
    import config
    hits = [_hit(f"Страна{i}", 0.60 - i * 0.001) for i in range(config.SURVEY_MAX_FRAGMENTS + 10)]
    picked, countries = _pick_survey(hits)
    assert len(picked) == config.SURVEY_MAX_FRAGMENTS
    # обрезка оставляет самые похожие
    assert picked[0]["similarity"] == 0.60


def test_pick_survey_unique_sorted_countries():
    hits = [_hit("Мальта", 0.50), _hit("Кипр", 0.51), _hit("Мальта", 0.48)]
    picked, countries = _pick_survey(hits)
    assert len(picked) == 3
    assert countries == ["Кипр", "Мальта"]


def test_pick_survey_empty():
    picked, countries = _pick_survey([])
    assert picked == [] and countries == []
