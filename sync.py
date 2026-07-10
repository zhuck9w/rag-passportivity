"""Индексация базы знаний: Notion → чанки → векторы → Supabase.
Запускается вручную или по расписанию (cron). Инкрементальная:
перечитывает только страницы, у которых изменился last_edited_time.
(Notion округляет last_edited_time до минуты — правка в ту же минуту,
что и предыдущая, может проскочить; страховка — недельный --full в cron.)"""
import argparse
from datetime import datetime, timezone

import config
import db
import notion_reader as nr
from chunker import chunk_page
from embedder import embed_texts


def run(full: bool, dry: bool) -> None:
    config.require("NOTION_TOKEN", "NOTION_KB_PAGE_ID", "VOYAGE_API_KEY",
                   "SUPABASE_URL", "SUPABASE_SECRET_KEY")
    started_at = datetime.now(timezone.utc).isoformat()
    cards = nr.list_cards()
    if not cards:
        raise SystemExit("Из Notion пришло 0 карточек — изменилась структура "
                         "страницы или отвалился доступ? Ничего не удаляю.")
    known = db.get_sync_state()
    state = {} if full else known
    changed = [c for c in cards if state.get(c.page_id) != c.last_edited]
    gone = sorted(set(known) - {c.page_id for c in cards})
    print(f"Карточек в Notion: {len(cards)}; обновить: {len(changed)}; удалить: {len(gone)}")

    if dry:
        for c in changed:
            print(f"  ~ {c.country} — {c.program}")
        for pid in gone:
            print(f"  - {pid}")
        return

    failed = 0
    chunks_written = 0
    for c in changed:
        try:
            markdown = nr.fetch_page_markdown(c.page_id)
            chunks = chunk_page(c, markdown)
            embeddings = embed_texts([ch.content for ch in chunks])
            db.replace_page_chunks(c, chunks, embeddings)
            chunks_written += len(chunks)
            print(f"  ok {c.country} — {c.program}: {len(chunks)} чанков")
        except Exception as e:  # одна плохая страница не срывает весь прогон
            failed += 1
            print(f"  FAIL {c.country} — {c.program}: {e}")

    if gone:
        db.delete_pages(gone)
        print(f"Удалены исчезнувшие страницы: {len(gone)}")

    try:  # журнал запусков; его сбой (например, таблицы ещё нет) не роняет синк
        db.log_sync(mode="full" if full else "incremental",
                    cards_total=len(cards), updated=len(changed) - failed,
                    failed=failed, deleted=len(gone),
                    chunks_written=chunks_written, started_at=started_at)
    except Exception as e:
        print(f"  предупреждение: не удалось записать журнал синхронизаций: {e}")

    if failed:
        raise SystemExit(f"Не проиндексировано страниц: {failed} — "
                         f"будут повторены при следующем запуске")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Синхронизация Notion → Supabase")
    parser.add_argument("--full", action="store_true",
                        help="переиндексировать все страницы, игнорируя состояние")
    parser.add_argument("--dry-run", action="store_true",
                        help="показать, что изменится, ничего не записывая")
    args = parser.parse_args()
    run(full=args.full, dry=args.dry_run)
