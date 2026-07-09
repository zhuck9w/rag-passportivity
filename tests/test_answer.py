from answer import build_user_message, _merge_history


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
