from retrieval import (_group_by_country, _pick_survey, _with_anchors,
                       build_hint, extract_rare_terms, parse_rewrite)


def test_with_anchors_dedup_and_prepend():
    frags = [{"id": 1, "content": "a"}, {"id": 2, "content": "b"}]
    anchors = [{"id": 2, "content": "дубль"}, {"id": 3, "content": "интро"}]
    merged = _with_anchors(frags, anchors)
    assert [f["id"] for f in merged] == [3, 1, 2]  # якорь впереди, без дублей

COUNTRIES = ["Мальта", "Португалия"]


def test_parse_ok_and_country_case_insensitive():
    raw = ('Вот JSON: {"query": "порог инвестиций Мальта", "countries": ["мальта"], '
           '"topic": "инвестиции и стоимость"}')
    q, matched, unknown, topic, survey, intent = parse_rewrite(raw, "исходный", COUNTRIES)
    assert q == "порог инвестиций Мальта"
    assert matched == ["Мальта"] and unknown == []
    assert topic == "инвестиции и стоимость"


def test_parse_two_countries():
    raw = '{"query": "сравнение порогов", "countries": ["Мальта", "Португалия"]}'
    q, matched, unknown, topic, survey, intent = parse_rewrite(raw, "и", COUNTRIES)
    assert matched == ["Мальта", "Португалия"] and unknown == []


def test_parse_empty_countries():
    q, matched, unknown, topic, survey, intent = parse_rewrite(
        '{"query": "все программы", "countries": []}', "и", COUNTRIES)
    assert matched == [] and unknown == []


def test_parse_garbage_falls_back():
    q, matched, unknown, topic, survey, intent = parse_rewrite(
        "не смогу помочь", "исходный вопрос", COUNTRIES)
    assert (q, matched, unknown, topic, survey, intent) == \
        ("исходный вопрос", [], [], "другое", False, "knowledge")


def test_parse_unknown_country_reported():
    q, matched, unknown, topic, survey, intent = parse_rewrite(
        '{"query": "q", "countries": ["Атлантида"]}', "и", COUNTRIES)
    assert matched == [] and unknown == ["Атлантида"]


def test_parse_valid_topic():
    q, matched, unknown, topic, survey, intent = parse_rewrite(
        '{"query": "q", "countries": [], "topic": "налоги"}', "и", COUNTRIES)
    assert topic == "налоги"


def test_parse_invalid_topic_becomes_other():
    q, matched, unknown, topic, survey, intent = parse_rewrite(
        '{"query": "q", "countries": [], "topic": "погода на Марсе"}', "и", COUNTRIES)
    assert topic == "другое"


def test_parse_missing_topic_becomes_other():
    q, matched, unknown, topic, survey, intent = parse_rewrite(
        '{"query": "q", "countries": []}', "и", COUNTRIES)
    assert topic == "другое"


def test_parse_survey_true():
    q, matched, unknown, topic, survey, intent = parse_rewrite(
        '{"query": "программы ВНЖ в ЕС", "countries": [], "survey": true}', "и", COUNTRIES)
    assert survey is True


def test_parse_survey_false():
    q, matched, unknown, topic, survey, intent = parse_rewrite(
        '{"query": "q", "countries": [], "survey": false}', "и", COUNTRIES)
    assert survey is False


def test_parse_survey_missing_defaults_false():
    q, matched, unknown, topic, survey, intent = parse_rewrite(
        '{"query": "q", "countries": []}', "и", COUNTRIES)
    assert survey is False


def test_parse_survey_garbage_defaults_false():
    for junk in ("null", "0", '""', "[]"):
        q, matched, unknown, topic, survey, intent = parse_rewrite(
            '{"query": "q", "countries": [], "survey": %s}' % junk, "и", COUNTRIES)
        assert survey is False, junk


# --- intent: маршрутизатор намерений ---

def test_parse_intent_valid_values():
    for value in ("knowledge", "meta", "smalltalk"):
        q, matched, unknown, topic, survey, intent = parse_rewrite(
            '{"query": "q", "countries": [], "intent": "%s"}' % value, "и", COUNTRIES)
        assert intent == value


def test_parse_intent_garbage_becomes_knowledge():
    for junk in ('"болтовня"', '"META"', "42", "null", "[]", "true"):
        q, matched, unknown, topic, survey, intent = parse_rewrite(
            '{"query": "q", "countries": [], "intent": %s}' % junk, "и", COUNTRIES)
        assert intent == "knowledge", junk


def test_parse_intent_missing_becomes_knowledge():
    q, matched, unknown, topic, survey, intent = parse_rewrite(
        '{"query": "q", "countries": []}', "и", COUNTRIES)
    assert intent == "knowledge"


# --- format_rule_blocks: правила только страниц из ответа, без наслоения ---

def _frag(pid):
    return {"page_id": pid, "content": "x", "similarity": 0.6, "country": "C"}


def test_rule_blocks_only_pages_present_in_fragments():
    from retrieval import format_rule_blocks
    frags = [_frag("p1"), _frag("p1"), _frag("p2")]
    rows = [
        {"page_id": "p1", "country": "Italy", "program": "Investor Visa", "rules": "правило А"},
        {"page_id": "p3", "country": "Italy", "program": "Digital Nomad", "rules": "правило Б"},
    ]
    out = format_rule_blocks(frags, rows)
    assert "Investor Visa" in out and "правило А" in out
    assert "Digital Nomad" not in out  # её фрагментов в ответе нет — не наслаиваем


def test_rule_blocks_ordered_by_fragment_share_and_capped():
    from retrieval import format_rule_blocks
    frags = [_frag("p2"), _frag("p2"), _frag("p2"), _frag("p1")]
    rows = [{"page_id": "p1", "country": "C", "program": "P1", "rules": "р1"},
            {"page_id": "p2", "country": "C", "program": "P2", "rules": "р2"}]
    out = format_rule_blocks(frags, rows)
    assert out.index("P2") < out.index("P1")  # кто ведёт ответ — тот первый
    assert format_rule_blocks(frags, rows, limit=1).count("[") == 1


def test_rule_blocks_empty_cases():
    from retrieval import format_rule_blocks
    assert format_rule_blocks([], []) is None
    assert format_rule_blocks([_frag("p1")], []) is None


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


def test_pick_survey_coverage_first():
    # лучший фрагмент каждой страны идёт раньше вторых фрагментов
    # более похожей страны — потолок режет глубину, а не страны
    hits = [_hit("A", 0.60), _hit("A", 0.59), _hit("B", 0.46)]
    picked, countries = _pick_survey(hits)
    assert [(h["country"], h["similarity"]) for h in picked] == \
        [("A", 0.60), ("B", 0.46), ("A", 0.59)]
    assert countries == ["A", "B"]


# --- extract_rare_terms: термины лексического спасателя ---

def test_rare_terms_lowercase_latin_in_russian_question():
    # «fiu» строчными в преимущественно кириллическом вопросе — реальный инцидент
    assert extract_rare_terms("fiu что такое?") == ["fiu"]


def test_rare_terms_caps_abbreviation_in_english_question():
    assert extract_rare_terms("What does NHR mean for taxes?") == ["NHR"]


def test_rare_terms_letter_plus_digits():
    assert extract_rare_terms("Что такое виза D7?") == ["D7"]


def test_rare_terms_english_without_abbreviations_empty():
    assert extract_rare_terms("what is the investment threshold in Malta?") == []


def test_rare_terms_pure_russian_empty():
    assert extract_rare_terms("какой порог на Мальте?") == []


def test_rare_terms_unique_ordered_capped_at_three():
    assert extract_rare_terms("FIU и ещё раз FIU, а также NHR, CIIP и MPRP") == \
        ["FIU", "NHR", "CIIP"]


# --- build_hint: подсказка «почти попал» ---

def test_build_hint_with_section():
    frag = {"country": "Vanuatu", "program": "CIIP", "section": "Основная информация"}
    assert build_hint(frag) == "Vanuatu — CIIP, раздел «Основная информация»"


def test_build_hint_without_section():
    assert build_hint({"country": "Vanuatu", "program": "CIIP", "section": ""}) == \
        "Vanuatu — CIIP"


# --- _group_by_country: перекладка обзорной выдачи блоками по странам ---

def test_group_by_country_contiguous_blocks():
    # вторые фрагменты подтягиваются к первым: фрагменты одной страны подряд,
    # порядок стран — по их лучшему фрагменту, внутри страны — как в выдаче
    frags = [_hit("A", 0.60), _hit("B", 0.55), _hit("C", 0.50),
             _hit("B", 0.49), _hit("A", 0.48)]
    grouped = _group_by_country(frags)
    assert [(h["country"], h["similarity"]) for h in grouped] == \
        [("A", 0.60), ("A", 0.48), ("B", 0.55), ("B", 0.49), ("C", 0.50)]


def test_group_by_country_keeps_composition():
    frags = [_hit("A", 0.60), _hit("B", 0.55), _hit("A", 0.48)]
    grouped = _group_by_country(frags)
    assert sorted(id(f) for f in grouped) == sorted(id(f) for f in frags)


def test_group_by_country_empty():
    assert _group_by_country([]) == []
