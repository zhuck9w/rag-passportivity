"""Сборка промпта и вызов Claude. Ответ строго по фрагментам базы."""
import re
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


def build_user_message(fragments: list[dict], question: str,
                       resolved: str | None = None) -> str:
    blocks = [f"--- Фрагмент {i} ---\n{f['content']}"
              for i, f in enumerate(fragments, 1)]
    tail = f"\n\nВопрос сотрудника: {question}"
    if resolved and resolved.strip().lower() != question.strip().lower():
        # Короткая реплика в диалоге («в Вануату») уже развёрнута
        # переформулировщиком в полный вопрос — отдаём модели готовый смысл,
        # чтобы она не объявляла реплику «неполной» и не копалась в истории.
        tail += (f"\nКак этот вопрос понимается с учётом контекста диалога: {resolved}"
                 "\nОтвечай именно на этот смысл; язык ответа — как в исходном "
                 "вопросе сотрудника.")
    return "Фрагменты базы знаний:\n\n" + "\n\n".join(blocks) + tail


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


def _to_mrkdwn(text: str) -> str:
    """Slack не понимает обычный markdown (**жирный**, заголовки #, [ссылки]()),
    а модель всё равно иногда так пишет. Конвертируем детерминированно,
    не полагаясь на дисциплину модели."""
    text = re.sub(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)", r"<\2|\1>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"^#{1,6}\s*(.+?)\s*$",
                  lambda m: "*" + m.group(1).strip().strip("*") + "*",
                  text, flags=re.M)
    text = re.sub(r"^(\s*)[-*]\s+", r"\1• ", text, flags=re.M)
    return text


def _sources_footer(fragments: list[dict]) -> str:
    seen = sorted({(f["country"].strip(), f["program"].strip(), f["notion_url"])
                   for f in fragments if f.get("notion_url")})
    if not seen:
        return ""
    lines = [f"• <{url}|{country} — {program}>" for country, program, url in seen]
    return "\n\nИсточники:\n" + "\n".join(lines)


def answer(question: str, fragments: list[dict], history: list[dict],
           resolved: str | None = None) -> str:
    msgs = _merge_history(
        history + [{"role": "user",
                    "text": build_user_message(fragments, question, resolved)}])
    resp = _anthropic().messages.create(
        model=config.ANSWER_MODEL, max_tokens=1200,
        system=_SYSTEM, messages=msgs)
    return _to_mrkdwn(resp.content[0].text) + _sources_footer(fragments)
