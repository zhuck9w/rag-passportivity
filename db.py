"""Вся работа с Supabase: хранение чанков, состояние синка, поиск."""
from supabase import create_client

import config

_sb = None


def sb():
    global _sb
    if _sb is None:
        config.require("SUPABASE_URL", "SUPABASE_SECRET_KEY")
        _sb = create_client(config.SUPABASE_URL, config.SUPABASE_SECRET_KEY)
    return _sb


def get_sync_state() -> dict[str, str]:
    rows = sb().table("sync_state").select("page_id, last_edited").execute().data
    return {r["page_id"]: r["last_edited"] for r in rows}


def replace_page_chunks(card, chunks, embeddings) -> None:
    """Сначала вставляем новые чанки, потом удаляем старые: бот работает
    параллельно с синком и не должен видеть страницу «пустой»."""
    rows = [{
        "page_id": card.page_id,
        "country": card.country,
        "program": card.program,
        "section": c.section,
        "status": card.status,
        "owners": card.owners,
        "notion_url": card.url,
        "page_edited_at": card.last_edited,
        "chunk_index": c.index,
        "content": c.content,
        "embedding": e,
    } for c, e in zip(chunks, embeddings)]
    new_ids = []
    if rows:
        res = sb().table("chunks").insert(rows).execute()
        new_ids = [r["id"] for r in res.data]
    query = sb().table("chunks").delete().eq("page_id", card.page_id)
    if new_ids:
        query = query.not_.in_("id", new_ids)
    query.execute()
    sb().table("sync_state").upsert(
        {"page_id": card.page_id, "last_edited": card.last_edited}).execute()


def delete_pages(page_ids: list[str]) -> None:
    for pid in page_ids:
        sb().table("chunks").delete().eq("page_id", pid).execute()
        sb().table("sync_state").delete().eq("page_id", pid).execute()
        try:  # таблицы program_rules может ещё не быть — чанки чистим всё равно
            sb().table("program_rules").delete().eq("page_id", pid).execute()
        except Exception as e:
            print(f"  предупреждение: не удалось очистить program_rules для {pid}: {e}")


def upsert_program_rules(card, rules: str) -> None:
    """«Правила ассистента» страницы: непустые — сохраняем, пустые — удаляем
    (раздел убрали из Notion → правило исчезает)."""
    if rules.strip():
        sb().table("program_rules").upsert({
            "page_id": card.page_id,
            "country": card.country,
            "program": card.program,
            "rules": rules,
            "updated_at": card.last_edited,
        }).execute()
    else:
        sb().table("program_rules").delete().eq("page_id", card.page_id).execute()


def get_program_rules(countries: list[str]) -> list[dict]:
    """Правила ассистента для стран запроса → [{country, program, rules}]."""
    if not countries:
        return []
    return (sb().table("program_rules")
            .select("country, program, rules")
            .in_("country", countries).execute().data)


def list_countries() -> list[str]:
    # считаем на сервере: select по всей таблице обрезается API на 1000 строках
    rows = sb().rpc("list_countries", {}).execute().data
    return [r["country"] for r in rows]


def search(embedding, country: str | None = None, k: int = config.TOP_K) -> list[dict]:
    resp = sb().rpc("match_chunks", {
        "query_embedding": embedding,
        "match_count": k,
        "filter_country": country,
    }).execute()
    return resp.data


def find_by_term(term: str, country: str | None = None, limit: int = 8) -> list[dict]:
    """Лексический поиск: чанки, где термин встречается буквально (без учёта
    регистра). Спасает вопросы про аббревиатуры (FIU, NHR, D7), которые
    векторный поиск кладёт ниже порога. Колонки — те же, что у match_chunks."""
    query = (sb().table("chunks")
             .select("id, page_id, country, program, section, status, "
                     "notion_url, page_edited_at, content")
             .ilike("content", "%" + term + "%"))
    if country:
        query = query.eq("country", country)
    rows = query.limit(limit).execute().data
    for r in rows:
        r["similarity"] = 1.0  # маркер «вне конкурса», как в page_anchors
    return rows


def page_anchors(country: str) -> list[dict]:
    """Первый чанк (chunk_index=0) каждой страницы страны: вводный раздел
    несёт паспорт программы и ключевые оговорки (например, ограничения по
    гражданству). При точечном вопросе добавляется в контекст гарантированно,
    вне конкурса похожести — чтобы оговорки не зависели от лотереи топ-K."""
    rows = (sb().table("chunks")
            .select("id, page_id, country, program, section, status, "
                    "notion_url, page_edited_at, content")
            .eq("country", country).eq("chunk_index", 0).execute().data)
    for r in rows:
        r["similarity"] = 1.0  # маркер «гарантированный контекст»
    return rows


def log_sync(mode: str, cards_total: int, updated: int, failed: int,
             deleted: int, chunks_written: int, started_at: str,
             programs: str = "") -> None:
    """Журнал запусков синхронизации (таблица sync_log)."""
    sb().table("sync_log").insert({
        "mode": mode,
        "cards_total": cards_total,
        "updated": updated,
        "failed": failed,
        "deleted": deleted,
        "chunks_written": chunks_written,
        "started_at": started_at,
        "programs": programs,
    }).execute()


def log_query(slack_user_id: str, user_name: str, channel_type: str,
              countries: list[str], topic: str, found: bool,
              fragments_count: int) -> None:
    """Журнал обращений. Приватность: текст вопроса сюда НЕ передаётся
    и НЕ сохраняется — только метаданные (кто, где, страны, тема, найдено ли)."""
    sb().table("query_log").insert({
        "slack_user_id": slack_user_id,
        "user_name": user_name,
        "channel_type": channel_type,
        "countries": ", ".join(countries),
        "topic": topic,
        "found": found,
        "fragments": fragments_count,
    }).execute()
