"""Подготовка запроса (переформулировка дешёвой моделью + определение
стран) и векторный поиск по базе с порогом похожести."""
import json
import re
from pathlib import Path

import anthropic

import config
import db
from embedder import embed_query

_client = None
_REWRITE_TEMPLATE = (Path(__file__).parent / "prompts" / "rewrite.txt").read_text(encoding="utf-8")


def _anthropic() -> anthropic.Anthropic:
    global _client
    if _client is None:
        config.require("ANTHROPIC_API_KEY")
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def _fmt_history(history: list[dict]) -> str:
    if not history:
        return "(пусто)"
    names = {"user": "Сотрудник", "assistant": "Бот"}
    return "\n".join(f"{names[m['role']]}: {m['text'][:500]}" for m in history[-8:])


def parse_rewrite(raw: str, fallback_query: str,
                  known_countries: list[str]) -> tuple[str, list[str], list[str], str, bool]:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return fallback_query, [], [], "другое", False
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return fallback_query, [], [], "другое", False
    query = (data.get("query") or fallback_query).strip()
    raw_countries = data.get("countries") or []
    if isinstance(raw_countries, str):
        raw_countries = [raw_countries]
    by_lower = {c.lower(): c for c in known_countries}
    matched, unknown = [], []
    for rc in raw_countries:
        rc = (rc or "").strip()
        if rc:
            hit = by_lower.get(rc.lower())
            (matched if hit else unknown).append(hit or rc)
    topic = data.get("topic")
    if not isinstance(topic, str) or topic.strip() not in config.TOPICS:
        topic = "другое"
    else:
        topic = topic.strip()
    survey = bool(data.get("survey"))
    return query, matched, unknown, topic, survey


def rewrite_question(question: str, history: list[dict],
                     countries: list[str]) -> tuple[str, list[str], list[str], str, bool]:
    prompt = (_REWRITE_TEMPLATE
              .replace("[[COUNTRIES]]", ", ".join(countries))
              .replace("[[TOPICS]]", ", ".join(config.TOPICS))
              .replace("[[HISTORY]]", _fmt_history(history))
              .replace("[[QUESTION]]", question))
    resp = _anthropic().messages.create(
        model=config.REWRITE_MODEL, max_tokens=300,
        messages=[{"role": "user", "content": prompt}])
    return parse_rewrite(resp.content[0].text, question, countries)


def _with_anchors(fragments: list[dict], anchors: list[dict]) -> list[dict]:
    """Подмешивает якорные чанки в начало выдачи, без дублей по id."""
    seen = {f["id"] for f in fragments}
    fresh = [a for a in anchors if a["id"] not in seen]
    return fresh + fragments


def _pick_survey(hits: list[dict]) -> tuple[list[dict], list[str]]:
    """Обзорный режим: мягкий порог, сортировка по похожести, обрезка до
    потолка, список уникальных стран вошедших фрагментов (для журнала)."""
    picked = [h for h in hits if h["similarity"] >= config.SURVEY_MIN_SIMILARITY]
    picked.sort(key=lambda h: h["similarity"], reverse=True)
    picked = picked[:config.SURVEY_MAX_FRAGMENTS]
    return picked, sorted({h["country"] for h in picked})


def retrieve(question: str, history: list[dict]) -> tuple[list[dict], str, list[str], str]:
    """→ (фрагменты, переформулированный запрос, распознанные страны, тема)."""
    countries = db.list_countries()
    query, matched, unknown, topic, survey = rewrite_question(question, history, countries)
    if unknown and not matched:
        # спрашивают про страну, которой нет в базе — честное «не нашёл»,
        # Claude не вызываем и не даём ему фрагменты про другие страны
        return [], query, [], topic
    vec = embed_query(query)
    if len(matched) >= 2:
        # сравнение стран: набираем фрагменты по каждой, чтобы одна страна
        # не вытеснила другую из топа
        per_country = max(config.TOP_K // len(matched), 3)
        fragments = []
        for c in matched:
            fragments += db.search(vec, c, per_country)
    elif not matched and survey:
        # обзорный вопрос без конкретной страны: глобальный топ-K не работает
        # (похожести размазаны по 31 стране ниже MIN_SIMILARITY), поэтому
        # берём лучшие фрагменты с каждой страны с мягким порогом
        hits = []
        for c in countries:
            hits += db.search(vec, c, config.SURVEY_PER_COUNTRY)
        fragments, hit_countries = _pick_survey(hits)
        return fragments, query, hit_countries, topic
    else:
        fragments = db.search(vec, matched[0] if matched else None)
    fragments = [f for f in fragments if f["similarity"] >= config.MIN_SIMILARITY]
    if fragments and matched and len(matched) <= 3:
        # Гарантированный контекст: первый чанк каждой страницы упомянутых
        # стран (вводный раздел с ключевыми оговорками) — добавляем всегда,
        # чтобы оговорки не проигрывали лотерею топ-K. Пустую выдачу не
        # «оживляем»: оффтоп-вопрос со страной так и остаётся «не нашёл».
        anchors = []
        for c in matched:
            anchors += db.page_anchors(c)
        fragments = _with_anchors(fragments, anchors)
    return fragments, query, matched, topic
