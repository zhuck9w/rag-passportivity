"""Сборка промпта и вызов Claude. Ответ строго по фрагментам базы."""
from pathlib import Path

import anthropic

import config

_client = None
_SYSTEM = (Path(__file__).parent / "prompts" / "system.txt").read_text(encoding="utf-8")


def _anthropic() -> anthropic.Anthropic:
    global _client
    if _client is None:
        config.require("ANTHROPIC_API_KEY")
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def build_user_message(fragments: list[dict], question: str) -> str:
    blocks = [f"--- Фрагмент {i} ---\n{f['content']}"
              for i, f in enumerate(fragments, 1)]
    return ("Фрагменты базы знаний:\n\n" + "\n\n".join(blocks) +
            f"\n\nВопрос сотрудника: {question}")


def _merge_history(history: list[dict]) -> list[dict]:
    """Claude требует строгого чередования user/assistant и старта с user."""
    merged: list[dict] = []
    for m in history[-10:]:
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1]["content"] += "\n" + m["text"]
        else:
            merged.append({"role": m["role"], "content": m["text"]})
    while merged and merged[0]["role"] == "assistant":
        merged.pop(0)
    return merged


def _sources_footer(fragments: list[dict]) -> str:
    seen = sorted({(f["country"], f["program"], f["notion_url"])
                   for f in fragments if f.get("notion_url")})
    if not seen:
        return ""
    lines = [f"• <{url}|{country} — {program}>" for country, program, url in seen]
    return "\n\nИсточники:\n" + "\n".join(lines)


def answer(question: str, fragments: list[dict], history: list[dict]) -> str:
    msgs = _merge_history(
        history + [{"role": "user",
                    "text": build_user_message(fragments, question)}])
    resp = _anthropic().messages.create(
        model=config.ANSWER_MODEL, max_tokens=1200,
        system=_SYSTEM, messages=msgs)
    return resp.content[0].text + _sources_footer(fragments)
