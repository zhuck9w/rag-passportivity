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
                  known_countries: list[str]) -> tuple[str, list[str], list[str], str]:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return fallback_query, [], [], "другое"
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return fallback_query, [], [], "другое"
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
    return query, matched, unknown, topic


def rewrite_question(question: str, history: list[dict],
                     countries: list[str]) -> tuple[str, list[str], list[str], str]:
    prompt = (_REWRITE_TEMPLATE
              .replace("[[COUNTRIES]]", ", ".join(countries))
              .replace("[[TOPICS]]", ", ".join(config.TOPICS))
              .replace("[[HISTORY]]", _fmt_history(history))
              .replace("[[QUESTION]]", question))
    resp = _anthropic().messages.create(
        model=config.REWRITE_MODEL, max_tokens=300,
        messages=[{"role": "user", "content": prompt}])
    return parse_rewrite(resp.content[0].text, question, countries)


def retrieve(question: str, history: list[dict]) -> tuple[list[dict], str, list[str], str]:
    """→ (фрагменты, переформулированный запрос, распознанные страны, тема)."""
    countries = db.list_countries()
    query, matched, unknown, topic = rewrite_question(question, history, countries)
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
    else:
        fragments = db.search(vec, matched[0] if matched else None)
    fragments = [f for f in fragments if f["similarity"] >= config.MIN_SIMILARITY]
    return fragments, query, matched, topic
