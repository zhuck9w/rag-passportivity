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


def test_history_merged_and_alternating():
    h = [{"role": "user", "text": "а"}, {"role": "user", "text": "б"},
         {"role": "assistant", "text": "в"}]
    merged = _merge_history(h)
    assert [m["role"] for m in merged] == ["user", "assistant"]
    assert merged[0]["content"] == "а\nб"


def test_history_cannot_start_with_assistant():
    merged = _merge_history([{"role": "assistant", "text": "привет"}])
    assert merged == []
