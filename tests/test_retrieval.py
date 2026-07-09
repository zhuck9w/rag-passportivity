from retrieval import parse_rewrite

COUNTRIES = ["Мальта", "Португалия"]


def test_parse_ok_and_country_case_insensitive():
    raw = 'Вот JSON: {"query": "порог инвестиций Мальта", "countries": ["мальта"]}'
    q, matched, unknown = parse_rewrite(raw, "исходный", COUNTRIES)
    assert q == "порог инвестиций Мальта"
    assert matched == ["Мальта"] and unknown == []


def test_parse_two_countries():
    raw = '{"query": "сравнение порогов", "countries": ["Мальта", "Португалия"]}'
    q, matched, unknown = parse_rewrite(raw, "и", COUNTRIES)
    assert matched == ["Мальта", "Португалия"] and unknown == []


def test_parse_empty_countries():
    q, matched, unknown = parse_rewrite('{"query": "все программы", "countries": []}', "и", COUNTRIES)
    assert matched == [] and unknown == []


def test_parse_garbage_falls_back():
    q, matched, unknown = parse_rewrite("не смогу помочь", "исходный вопрос", COUNTRIES)
    assert (q, matched, unknown) == ("исходный вопрос", [], [])


def test_parse_unknown_country_reported():
    q, matched, unknown = parse_rewrite('{"query": "q", "countries": ["Атлантида"]}', "и", COUNTRIES)
    assert matched == [] and unknown == ["Атлантида"]
