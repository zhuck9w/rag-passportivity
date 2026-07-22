from chunker import build_passport, split_rules, split_sections, split_long, chunk_page
from notion_reader import Card

CARD = Card(page_id="p1", program="Golden Visa", country="Мальта",
            status="Actual", owners="", url="https://notion.so/x",
            last_edited="2026-02-19T16:49:00.000Z")


def test_passport_format():
    p = build_passport("Мальта", "Golden Visa", "Требования", "Actual", "2026-02-19")
    assert p == "[Мальта — Golden Visa | Раздел: Требования | Статус: Actual, обновлено 2026-02-19]"


def test_passport_without_optional_parts():
    assert build_passport("", "Golden Visa", "", "", "") == "[Golden Visa]"


def test_split_sections():
    md = "вступление\n## Требования\nтекст а\n## Сроки\nтекст б"
    assert [s[0] for s in split_sections(md)] == ["", "Требования", "Сроки"]


def test_split_long_overlap():
    text = "\n".join(f"строка {i} " + "х" * 90 for i in range(40))
    parts = split_long(text, max_chars=1000, overlap=200)
    assert len(parts) > 1
    assert all(len(p) <= 1400 for p in parts)
    assert parts[1].splitlines()[0] in parts[0]  # перехлёст: начало II есть в I


def test_overlap_with_long_paragraphs():
    # юниты длиннее overlap: перехлёст всё равно должен существовать
    text = "\n".join("абзац " + "х" * 400 for _ in range(10))
    parts = split_long(text, max_chars=1000, overlap=200)
    assert len(parts) > 1
    assert parts[1][:100] in parts[0]


def test_small_table_stays_whole():
    rows = "\n".join("| ячейка | ячейка |" for _ in range(5))
    parts = split_long("до\n" + rows + "\nпосле", max_chars=2000, overlap=50)
    assert len(parts) == 1


def test_big_table_split_repeats_header():
    header = "| Страна | Сумма |\n|---|---|"
    rows = "\n".join(f"| строка {i} | {i} евро |" for i in range(60))
    parts = split_long(header + "\n" + rows, max_chars=400, overlap=50)
    assert len(parts) > 1
    assert all(p.splitlines()[0] == "| Страна | Сумма |" for p in parts)


# --- split_rules: раздел «Правила ассистента» уходит из индекса ---

def test_split_rules_absent_rules_empty_content_untouched():
    md = "вступление\n## Требования\nтекст а\n## Сроки\nтекст б"
    rules, content = split_rules(md)
    assert rules == ""
    assert content == md  # байт-в-байт


def test_split_rules_emoji_case_extra_spaces():
    md = "##  🤖  ПРАВИЛА   АССИСТЕНТА  \nвсегда упоминай менеджера\n## Сроки\nтекст"
    rules, content = split_rules(md)
    assert rules == "всегда упоминай менеджера"
    assert "менеджера" not in content
    assert "## Сроки" in content and "текст" in content


def test_split_rules_middle_keeps_before_and_after_with_headers():
    md = ("вступление\n## Требования\nтекст а\n"
          "## Правила ассистента\nправило 1\nправило 2\n"
          "## Сроки\nтекст б")
    rules, content = split_rules(md)
    assert rules == "правило 1\nправило 2"
    assert content == "вступление\n## Требования\nтекст а\n## Сроки\nтекст б"


def test_split_rules_two_sections_glued():
    md = ("## Правила ассистента\nправило 1\n"
          "## Сроки\nтекст\n"
          "### 🤖 правила ассистента\nправило 2")
    rules, content = split_rules(md)
    assert rules == "правило 1\n\nправило 2"
    assert content == "## Сроки\nтекст"


def test_split_rules_real_editors_title():
    # реальный заголовок редакторов, с нумерацией; FAQ для ИИ-бота — знание,
    # а не правила: остаётся в контенте
    md = ("## Требования\nтекст а\n"
          "## 28. Контрольные правила для ответов ИИ-бота\n"
          "1. Если вопрос про пороги — отвечать по разделу 6.\n"
          "## 26. FAQ для ИИ-бота\nВ: вопрос?\nО: ответ.")
    rules, content = split_rules(md)
    assert "по разделу 6" in rules
    assert "по разделу 6" not in content
    assert "В: вопрос?" in content and "FAQ" in content


def test_split_rules_plain_pravila_not_cut():
    md = "## Правила программы\nэто знание, не правила бота"
    rules, content = split_rules(md)
    assert rules == ""
    assert content == md


def test_split_rules_loose_assistant_title_cut():
    # асимметрия осознанная: «правила»+«ассистент» в заголовке считаем
    # правилами — хуже, если инструкции для бота утекут в контент и будут
    # процитированы сотруднику как знание базы
    md = "## Правила ассистента по срокам\nвсегда уточняй даты"
    rules, content = split_rules(md)
    assert rules == "всегда уточняй даты"


def test_chunk_page_passports_everywhere():
    md = "## Требования\n" + "т" * 3000
    chunks = chunk_page(CARD, md)
    assert len(chunks) >= 2
    assert all(c.content.startswith("[Мальта — Golden Visa") for c in chunks)
    assert all(c.section == "Требования" for c in chunks)
