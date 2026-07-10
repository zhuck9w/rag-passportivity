from answer import build_user_message, _merge_history, _to_mrkdwn


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
