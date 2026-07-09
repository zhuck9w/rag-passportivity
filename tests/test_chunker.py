from chunker import build_passport, split_sections, split_long, chunk_page
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


def test_chunk_page_passports_everywhere():
    md = "## Требования\n" + "т" * 3000
    chunks = chunk_page(CARD, md)
    assert len(chunks) >= 2
    assert all(c.content.startswith("[Мальта — Golden Visa") for c in chunks)
    assert all(c.section == "Требования" for c in chunks)
