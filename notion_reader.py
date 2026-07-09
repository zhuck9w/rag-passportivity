"""Чтение базы знаний из Notion. Только чтение: databases.query и
blocks.children.list, никаких вызовов записи."""
import time
from dataclasses import dataclass

from notion_client import Client
from notion_client.errors import HTTPResponseError, RequestTimeoutError

import config

_client = None


def notion() -> Client:
    global _client
    if _client is None:
        config.require("NOTION_TOKEN")
        _client = Client(auth=config.NOTION_TOKEN)
    return _client


def notion_call(fn, **kwargs):
    """Вызов API с повтором при rate limit (3 rps), таймаутах и сбоях 5xx.
    HTTPResponseError ловит и APIResponseError (это её подкласс), и «сырые»
    502/503 от шлюзов, у которых тело ответа не в формате Notion."""
    for attempt in range(5):
        try:
            return fn(**kwargs)
        except RequestTimeoutError:
            if attempt == 4:
                raise
            time.sleep(1.5 * (attempt + 1))
        except HTTPResponseError as e:
            if e.status not in (429, 500, 502, 503, 504) or attempt == 4:
                raise
            retry_after = float(e.headers.get("retry-after") or 0)
            time.sleep(max(retry_after, 1.5 * (attempt + 1)))


@dataclass
class Card:
    page_id: str
    program: str
    country: str
    status: str
    owners: str
    url: str
    last_edited: str


def _prop_text(prop: dict) -> str:
    t = prop.get("type", "")
    v = prop.get(t)
    if not v:
        return ""
    if t in ("title", "rich_text"):
        return "".join(rt.get("plain_text", "") for rt in v)
    if t in ("select", "status"):
        return v.get("name", "")
    if t == "multi_select":
        return ", ".join(o.get("name", "") for o in v)
    if t == "people":
        return ", ".join(p.get("name", "") for p in v if p.get("name"))
    if t == "date":
        return v.get("start", "") or ""
    return ""


def _title_of(props: dict) -> str:
    for prop in props.values():
        if prop.get("type") == "title":
            return _prop_text(prop)
    return ""


def list_databases() -> list[str]:
    """Ищем child_database рекурсивно: базы бывают внутри колонок и тогглов."""
    config.require("NOTION_KB_PAGE_ID")
    ids: list[str] = []

    def scan(block_id: str) -> None:
        for b in _children(block_id):
            if b["type"] == "child_database":
                ids.append(b["id"])
            elif b.get("has_children") and b["type"] != "child_page":
                scan(b["id"])

    scan(config.NOTION_KB_PAGE_ID)
    return ids


def list_cards() -> list[Card]:
    cards = []
    for db_id in list_databases():
        cursor = None
        while True:
            resp = notion_call(notion().databases.query,
                               database_id=db_id, start_cursor=cursor, page_size=100)
            for page in resp["results"]:
                props = page["properties"]
                cards.append(Card(
                    page_id=page["id"],
                    program=_title_of(props),
                    country=_prop_text(props.get(config.COUNTRY_PROP, {})),
                    status=_prop_text(props.get(config.STATUS_PROP, {})),
                    owners=_prop_text(props.get(config.OWNER_PROP, {})) if config.OWNER_PROP else "",
                    url=page["url"],
                    last_edited=page["last_edited_time"],
                ))
            cursor = resp.get("next_cursor")
            if not cursor:
                break
    return cards


def _children(block_id: str) -> list[dict]:
    out, cursor = [], None
    while True:
        resp = notion_call(notion().blocks.children.list,
                           block_id=block_id, start_cursor=cursor)
        out += resp["results"]
        cursor = resp.get("next_cursor")
        if not cursor:
            return out


_LIST_TYPES = ("bulleted_list_item", "numbered_list_item", "toggle", "to_do")


def _rich(rt_list: list[dict]) -> str:
    out = []
    for rt in rt_list:
        text = rt.get("plain_text", "")
        href = rt.get("href")
        out.append(f"[{text}]({href})" if href else text)
    return "".join(out)


def _block_lines(block: dict, depth: int = 0) -> list[str]:
    t = block["type"]
    d = block.get(t, {})
    pad = "  " * depth
    lines: list[str] = []
    handled_children = False

    if t == "paragraph":
        text = _rich(d.get("rich_text", []))
        if text.strip():
            lines.append(pad + text)
    elif t == "heading_1":
        lines.append("# " + _rich(d.get("rich_text", [])))
    elif t == "heading_2":
        lines.append("## " + _rich(d.get("rich_text", [])))
    elif t == "heading_3":
        lines.append("### " + _rich(d.get("rich_text", [])))
    elif t in ("bulleted_list_item", "toggle"):
        lines.append(pad + "- " + _rich(d.get("rich_text", [])))
    elif t == "numbered_list_item":
        lines.append(pad + "1. " + _rich(d.get("rich_text", [])))
    elif t == "to_do":
        mark = "x" if d.get("checked") else " "
        lines.append(f"{pad}- [{mark}] " + _rich(d.get("rich_text", [])))
    elif t in ("callout", "quote"):
        lines.append(pad + "> " + _rich(d.get("rich_text", [])))
    elif t == "code":
        lines.append("```")
        lines.append(_rich(d.get("rich_text", [])))
        lines.append("```")
    elif t == "divider":
        lines.append("---")
    elif t == "table":
        rows = [r for r in _children(block["id"]) if r["type"] == "table_row"]
        cells = [[_rich(c) for c in r["table_row"].get("cells", [])] for r in rows]
        if cells:
            lines.append("| " + " | ".join(cells[0]) + " |")
            lines.append("|" + "---|" * len(cells[0]))
            for row in cells[1:]:
                lines.append("| " + " | ".join(row) + " |")
        handled_children = True
    elif t in ("child_page", "child_database"):
        handled_children = True  # вложенные страницы не разворачиваем
    # image, file, embed, bookmark и прочее — пропускаем молча

    if block.get("has_children") and not handled_children:
        child_depth = depth + 1 if t in _LIST_TYPES else depth
        for child in _children(block["id"]):
            lines += _block_lines(child, child_depth)
    return lines


def fetch_page_markdown(page_id: str) -> str:
    lines: list[str] = []
    for block in _children(page_id):
        lines += _block_lines(block)
    return "\n".join(lines)
