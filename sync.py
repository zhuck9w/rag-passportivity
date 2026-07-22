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


def keep_labeled(cards: list) -> tuple[list, int]:
    """Правило: страница без лейбла страны для бота не существует.
    Снять лейбл в Notion = вывести страницу из индекса (чанки вычистятся
    как «исчезнувшие»); черновики без страны не индексируются вовсе."""
    labeled = [c for c in cards if c.country]
    return labeled, len(cards) - len(labeled)


def too_many_unlabeled(total: int, skipped: int) -> bool:
    """Предохранитель: массовая потеря лейблов — это не «вывели страницы»,
    а смена структуры или переименование свойства Country. Не удаляем."""
    return skipped >= max(5, total // 4)


def run(full: bool, dry: bool) -> None:
    config.require("NOTION_TOKEN", "NOTION_KB_PAGE_ID", "VOYAGE_API_KEY",
                   "SUPABASE_URL", "SUPABASE_SECRET_KEY")
    started_at = datetime.now(timezone.utc).isoformat()
    raw_cards = nr.list_cards()
    cards, skipped = keep_labeled(raw_cards)
    if skipped:
        print(f"Пропущено карточек без лейбла страны: {skipped} — бот их не индексирует")
        if too_many_unlabeled(len(raw_cards), skipped):
            raise SystemExit("Слишком много карточек без страны — похоже на смену "
                             "структуры или переименование свойства Country. "
                             "Ничего не удаляю.")
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
    programs: list[str] = []  # что именно поменялось — для журнала
    for c in changed:
        try:
            markdown = nr.fetch_page_markdown(c.page_id)
            chunks = chunk_page(c, markdown)
            embeddings = embed_texts([ch.content for ch in chunks])
            db.replace_page_chunks(c, chunks, embeddings)
            chunks_written += len(chunks)
            programs.append(f"{c.country} — {c.program}")
            print(f"  ok {c.country} — {c.program}: {len(chunks)} чанков")
        except Exception as e:  # одна плохая страница не срывает весь прогон
            failed += 1
            programs.append(f"FAIL: {c.country} — {c.program}")
            print(f"  FAIL {c.country} — {c.program}: {e}")

    if gone:
        db.delete_pages(gone)
        programs += [f"удалена страница {pid}" for pid in gone]
        print(f"Удалены исчезнувшие страницы: {len(gone)}")

    if programs:
        # журнал пишем только когда что-то реально поменялось; «жив ли cron»
        # видно по sync.log. Сбой журнала (нет таблицы и т.п.) синк не роняет.
        try:
            db.log_sync(mode="full" if full else "incremental",
                        cards_total=len(cards), updated=len(changed) - failed,
                        failed=failed, deleted=len(gone),
                        chunks_written=chunks_written, started_at=started_at,
                        programs="; ".join(programs))
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
