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
from chunker import chunk_page, split_rules
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


# Самая маленькая база в Notion — 3 карточки (на 2026-10-31: 8/21/12/3).
# Если база пропала из обхода целиком (переехала на подстраницу — сканер туда
# не спускается; заменена связанным представлением; у интеграции отозвали
# доступ), все её страницы разом оказываются «исчезнувшими».
MASS_DELETE_MIN = 3


def too_many_gone(gone: int) -> bool:
    """Предохранитель удаления: столько исчезнувших страниц за один прогон —
    скорее потерянная база, чем удалённые программы. Удаление откладываем до
    явного --allow-mass-delete, обновления при этом идут как обычно."""
    return gone >= MASS_DELETE_MIN


def split_gone(gone: list[str], unlabeled: set[str],
               allow_mass_delete: bool) -> tuple[list[str], list[str]]:
    """→ (удалить сейчас, отложить). Страницы, с которых сняли лейбл страны,
    удаляются всегда: снятие лейбла — штатный способ вывести страницу из бота,
    а массовую потерю лейблов уже ловит too_many_unlabeled. Под предохранитель
    попадают только страницы, пропавшие из обхода Notion совсем."""
    vanished = [p for p in gone if p not in unlabeled]
    if allow_mass_delete or not too_many_gone(len(vanished)):
        return gone, []
    return [p for p in gone if p in unlabeled], vanished


def run(full: bool, dry: bool, allow_mass_delete: bool = False) -> None:
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
    unlabeled = {c.page_id for c in raw_cards if not c.country}
    # held — исчезнувшие, но удаление отложено предохранителем
    gone, held = split_gone(gone, unlabeled, allow_mass_delete)
    print(f"Карточек в Notion: {len(cards)}; обновить: {len(changed)}; удалить: {len(gone)}")
    if held:
        print(f"ВНИМАНИЕ: ОТЛОЖЕНО удаление страниц: {len(held)} — они разом "
              f"пропали из обхода Notion (похоже на перенос или потерю целой "
              f"базы). Если удаление намеренное: sync.py --allow-mass-delete")

    if dry:
        for c in changed:
            print(f"  ~ {c.country} — {c.program}")
        for pid in gone:
            print(f"  - {pid}")
        for pid in held:
            print(f"  ! {pid} (удаление отложено)")
        return

    failed = 0
    chunks_written = 0
    programs: list[str] = []  # что именно поменялось — для журнала
    for c in changed:
        try:
            markdown = nr.fetch_page_markdown(c.page_id)
            rules, content = split_rules(markdown)
            chunks = chunk_page(c, content)
            embeddings = embed_texts([ch.content for ch in chunks])
            db.replace_page_chunks(c, chunks, embeddings)
            try:
                # «Правила ассистента» — в отдельную таблицу, не в индекс.
                # Сбой (таблицы ещё нет и т.п.) чанки не откатывает — как log_sync.
                db.upsert_program_rules(c, rules)
            except Exception as e:
                print(f"  предупреждение: не удалось обновить правила ассистента "
                      f"({c.country} — {c.program}): {e}")
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
    if held:
        # пишем в журнал каждый прогон, пока ситуация не разрешена: это и есть сигнал
        programs.append(f"ОТЛОЖЕНО удаление страниц: {len(held)} (предохранитель)")

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

    problems = []
    if failed:
        problems.append(f"Не проиндексировано страниц: {failed} — "
                        f"будут повторены при следующем запуске")
    if held:
        problems.append(f"ОТЛОЖЕНО удаление страниц: {len(held)} — проверьте "
                        f"Notion; если удаление намеренное, запустите "
                        f"sync.py --allow-mass-delete")
    if problems:
        raise SystemExit("\n".join(problems))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Синхронизация Notion → Supabase")
    parser.add_argument("--full", action="store_true",
                        help="переиндексировать все страницы, игнорируя состояние")
    parser.add_argument("--dry-run", action="store_true",
                        help="показать, что изменится, ничего не записывая")
    parser.add_argument("--allow-mass-delete", action="store_true",
                        help=f"удалить исчезнувшие страницы, даже если их "
                             f"{MASS_DELETE_MIN} и больше (по умолчанию — отложить)")
    args = parser.parse_args()
    run(full=args.full, dry=args.dry_run, allow_mass_delete=args.allow_mass_delete)
