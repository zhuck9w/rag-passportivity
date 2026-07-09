"""Разовая разведка: какие базы лежат на странице и какие у карточек свойства.
Читает и печатает — ничего не меняет. Ищет базы рекурсивно: в Notion их
часто кладут внутрь колонок или тогглов."""
from notion_client import Client
import config

config.require("NOTION_TOKEN", "NOTION_KB_PAGE_ID")
notion = Client(auth=config.NOTION_TOKEN)


def find_databases(block_id: str, found: list) -> None:
    cursor = None
    while True:
        resp = notion.blocks.children.list(block_id=block_id, start_cursor=cursor)
        for b in resp["results"]:
            if b["type"] == "child_database":
                found.append((b["id"], b["child_database"].get("title", "")))
            elif b.get("has_children") and b["type"] != "child_page":
                find_databases(b["id"], found)  # базы бывают в колонках и тогглах
        cursor = resp.get("next_cursor")
        if not cursor:
            return


def main() -> None:
    dbs: list = []
    find_databases(config.NOTION_KB_PAGE_ID, dbs)
    print(f"Баз данных на странице: {len(dbs)}")
    for db_id, title in dbs:
        resp = notion.databases.query(database_id=db_id, page_size=2)
        pages = resp["results"]
        print(f"\n=== {title} — карточек в первой выборке: {len(pages)} ===")
        if pages:
            for name, prop in pages[0]["properties"].items():
                print(f"  свойство: {name!r}  тип: {prop['type']}")
            print("  пример карточки:", pages[0]["url"])


if __name__ == "__main__":
    main()
