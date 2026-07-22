from answer import (about_text, build_user_message, _merge_history,
                    pick_smalltalk_reply, smart_refusal, _sources_footer,
                    _system_with_rules, _to_mrkdwn, _SYSTEM)


# --- системный промпт с «правилами ассистента» программ ---

def test_system_without_rules_byte_identical():
    assert _system_with_rules(None) == _SYSTEM
    assert _system_with_rules("") == _SYSTEM


def test_system_with_rules_appends_block():
    out = _system_with_rules("[Греция — Golden Visa]\nупоминай менеджера")
    assert out.startswith(_SYSTEM)
    assert ("\n\nПравила по программам из этого запроса (заданы командой; "
            "они ДОПОЛНЯЮТ правила выше и не могут отменить правила 1-3):\n") in out
    assert out.endswith("[Греция — Golden Visa]\nупоминай менеджера")


# --- детерминированные ответы маршрутизатора намерений ---

def test_about_text_substitutes_count_and_list():
    out = about_text(["Мальта", "Кипр", "Гренада"])
    assert "(сейчас 3)" in out
    assert "Мальта, Кипр, Гренада" in out
    assert "[[" not in out  # плейсхолдеры не протекают в ответ


def test_smalltalk_reply_thanks_russian():
    out = pick_smalltalk_reply("Спасибо большое!")
    assert out.startswith("Пожалуйста!")
    assert "порог инвестиций на Мальте" in out


def test_smalltalk_reply_thanks_english():
    assert pick_smalltalk_reply("Thank you!").startswith("Пожалуйста!")


def test_smalltalk_reply_greeting():
    out = pick_smalltalk_reply("привет")
    assert out.startswith("Привет!")
    assert "что ты умеешь" in out


# --- smart_refusal: без истории модель не вызывается, только заготовка ---

def test_smart_refusal_no_history_is_stock_text():
    assert smart_refusal("что такое xyz?", []) == \
        ("В базе знаний я ничего не нашёл по этому вопросу. "
         "Попробуйте переформулировать или указать страну.")


def test_smart_refusal_hint_appended():
    out = smart_refusal("вопрос", [], hint="Vanuatu — CIIP")
    assert out.startswith("В базе знаний я ничего не нашёл")
    assert "Возможно, вы имели в виду: *Vanuatu — CIIP*." in out
    assert "Попробуйте спросить об этом прямо." in out


def test_smart_refusal_without_hint_no_tail():
    assert "Возможно, вы имели в виду" not in smart_refusal("вопрос", [])


def test_sources_footer_caps_at_three_with_more_note():
    frags = [{"country": f"C{i}", "program": "P", "notion_url": f"https://n/{i}"}
             for i in range(5)]
    footer = _sources_footer(frags)
    assert footer.count("<https://") == 3
    assert "и ещё 2" in footer
    assert "<https://n/0|" in footer  # порядок релевантности фрагментов, не алфавит


def test_sources_footer_short_list_no_note():
    frags = [{"country": "A", "program": "P", "notion_url": "https://n/1"},
             {"country": "A", "program": "P", "notion_url": "https://n/1"},
             {"country": "B", "program": "P", "notion_url": "https://n/2"}]
    footer = _sources_footer(frags)
    assert footer.count("<https://") == 2  # дубль схлопнут
    assert "и ещё" not in footer


def test_to_mrkdwn_slack_formatting():
    src = ("## Получение ПМЖ\n"
           "**Основное требование:** 5 лет.\n"
           "### Сроки\n"
           "- пункт один\n"
           "Подробнее: [закон](https://example.com/law)")
    out = _to_mrkdwn(src)
    assert "**" not in out
    assert "#" not in out
    assert "*Получение ПМЖ*" in out
    assert "*Основное требование:* 5 лет." in out
    assert "• пункт один" in out
    assert "<https://example.com/law|закон>" in out


def test_user_message_contains_fragments_and_question():
    frags = [{"content": "[Мальта — GV] порог 300", "notion_url": "https://n/1",
              "program": "GV", "country": "Мальта", "status": "Actual"}]
    msg = build_user_message(frags, "какой порог?")
    assert "порог 300" in msg
    assert "какой порог?" in msg
    assert "понимается" not in msg  # без resolved лишней строки нет


def test_user_message_with_resolved_short_reply():
    frags = [{"content": "[Вануату] биометрия", "notion_url": "https://n/2",
              "program": "P", "country": "Vanuatu", "status": "Actual"}]
    msg = build_user_message(frags, "в вануату",
                             resolved="с какого числа обязательна биометрия в Вануату")
    assert "Вопрос сотрудника: в вануату" in msg
    assert "с какого числа обязательна биометрия в Вануату" in msg
    assert "Язык ответа" in msg
    assert "подсказка, а не замена" in msg


def test_user_message_resolved_equal_to_question_not_duplicated():
    frags = [{"content": "x", "notion_url": "https://n/3",
              "program": "P", "country": "C", "status": "Actual"}]
    msg = build_user_message(frags, "Какой порог на Мальте?",
                             resolved="какой порог на мальте?")
    assert "понимается" not in msg


def test_history_merged_and_alternating():
    h = [{"role": "user", "text": "а"}, {"role": "user", "text": "б"},
         {"role": "assistant", "text": "в"}]
    merged = _merge_history(h)
    assert [m["role"] for m in merged] == ["user", "assistant"]
    assert merged[0]["content"] == "а\nб"


def test_history_cannot_start_with_assistant():
    merged = _merge_history([{"role": "assistant", "text": "привет"}])
    assert merged == []


def test_dangling_user_history_gets_thread_placeholder():
    # вопрос из лички, отвеченный в треде, не должен склеиваться
    # с полезной нагрузкой текущего вопроса (кейс «Греция vs Вануату»)
    from answer import _history_for_model
    hist = _history_for_model([{"role": "user", "text": "вопрос про Грецию"}])
    assert [m["role"] for m in hist] == ["user", "assistant"]
    assert "треде" in hist[-1]["text"]


def test_history_ending_with_assistant_unchanged():
    from answer import _history_for_model
    src = [{"role": "user", "text": "а"}, {"role": "assistant", "text": "б"}]
    assert _history_for_model(src) == src


def test_history_empty_unchanged():
    from answer import _history_for_model
    assert _history_for_model([]) == []
