"""Markdown страницы → чанки. Каждый чанк начинается с «паспорта»:
[Страна — Программа | Раздел: ... | Статус: ..., обновлено ...] —
это главный механизм, не дающий перепутать похожие программы."""
from dataclasses import dataclass

import config
from notion_reader import Card


@dataclass
class Chunk:
    content: str
    section: str
    index: int


def build_passport(country: str, program: str, section: str,
                   status: str, edited_date: str) -> str:
    parts = [f"{country} — {program}" if country else program]
    if section:
        parts.append(f"Раздел: {section}")
    if status:
        parts.append(f"Статус: {status}" +
                     (f", обновлено {edited_date}" if edited_date else ""))
    return "[" + " | ".join(parts) + "]"


def split_sections(markdown: str) -> list[tuple[str, str]]:
    """Режем по заголовкам #/##/### → [(название раздела, текст), ...]."""
    sections: list[tuple[str, str]] = []
    title, buf = "", []
    for line in markdown.splitlines():
        if line.startswith("#"):
            if "\n".join(buf).strip():
                sections.append((title, "\n".join(buf).strip()))
            title, buf = line.lstrip("#").strip(), []
        else:
            buf.append(line)
    if "\n".join(buf).strip():
        sections.append((title, "\n".join(buf).strip()))
    return sections


def _units(text: str) -> list[str]:
    """Строки текста; подряд идущие строки таблицы — один блок."""
    units, table = [], []
    for line in text.splitlines():
        if line.lstrip().startswith("|"):
            table.append(line)
        else:
            if table:
                units.append("\n".join(table))
                table = []
            if line.strip():
                units.append(line)
    if table:
        units.append("\n".join(table))
    return units


def _split_table(table: str, max_chars: int) -> list[str]:
    """Огромную таблицу режем по строкам, повторяя шапку в каждом куске:
    иначе хвост таблицы не влезет в лимит эмбеддинга и станет ненаходимым."""
    lines = table.splitlines()
    if len(table) <= max_chars or len(lines) < 4:
        return [table]
    header = lines[:2]  # строка шапки + разделитель |---|
    header_size = sum(len(line) + 1 for line in header)
    pieces, cur, size = [], list(header), header_size
    for row in lines[2:]:
        if size + len(row) > max_chars and len(cur) > 2:
            pieces.append("\n".join(cur))
            cur, size = list(header), header_size
        cur.append(row)
        size += len(row) + 1
    pieces.append("\n".join(cur))
    return pieces


def _hard_split(unit: str, max_chars: int, overlap: int) -> list[str]:
    """Строку длиннее max_chars (абзац без переносов) режем жёстко,
    с посимвольным перехлёстом."""
    step = max(max_chars - overlap, 1)
    return [unit[i:i + max_chars] for i in range(0, len(unit), step)]


def split_long(text: str, max_chars: int, overlap: int) -> list[str]:
    units: list[str] = []
    for u in _units(text):
        if u.lstrip().startswith("|"):
            units += _split_table(u, max_chars)
        elif len(u) > max_chars:
            units += _hard_split(u, max_chars, overlap)
        else:
            units.append(u)

    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for u in units:
        if size + len(u) > max_chars and buf:
            chunks.append("\n".join(buf))
            tail, tail_size = [], 0
            for prev in reversed(buf):
                if tail_size + len(prev) > overlap:
                    break
                tail.insert(0, prev)
                tail_size += len(prev)
            if not tail and not buf[-1].lstrip().startswith("|"):
                # последний юнит длиннее overlap — берём его хвост посимвольно
                # (после кусков таблиц перехлёст не нужен: у них своя шапка)
                tail = [buf[-1][-overlap:]]
                tail_size = len(tail[0])
            buf, size = tail, tail_size
        buf.append(u)
        size += len(u)
    if buf:
        chunks.append("\n".join(buf))
    return chunks


def chunk_page(card: Card, markdown: str) -> list[Chunk]:
    date = card.last_edited[:10] if card.last_edited else ""
    result: list[Chunk] = []
    for title, text in split_sections(markdown) or [("", markdown)]:
        for piece in split_long(text, config.CHUNK_MAX_CHARS, config.CHUNK_OVERLAP_CHARS):
            if (len(piece.strip()) < config.CHUNK_MIN_CHARS
                    and result and result[-1].section == title):
                # мелочь клеим к предыдущему куску ТОГО ЖЕ раздела:
                # чужой паспорт не должен врать про раздел
                result[-1].content += "\n" + piece
                continue
            passport = build_passport(card.country, card.program, title,
                                      card.status, date)
            result.append(Chunk(content=passport + "\n" + piece,
                                section=title, index=len(result)))
    return result
