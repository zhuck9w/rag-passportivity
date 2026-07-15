"""Сборка промпта и вызов Claude. Ответ строго по фрагментам базы."""
import re
from pathlib import Path

import anthropic

import config

_client = None
_SYSTEM = (Path(__file__).parent / "prompts" / "system.txt").read_text(encoding="utf-8")
_ABOUT_PATH = Path(__file__).parent / "prompts" / "about.txt"


def about_text(countries: list[str]) -> str:
    """Детерминированная «визитка» бота для intent=meta: шаблон из
    prompts/about.txt с подстановкой числа и списка стран базы."""
    return (_ABOUT_PATH.read_text(encoding="utf-8")
            .replace("[[COUNT]]", str(len(countries)))
            .replace("[[COUNTRIES]]", ", ".join(countries))
            .strip())


def pick_smalltalk_reply(question: str) -> str:
    """Детерминированный ответ на приветствие/благодарность (intent=smalltalk):
    собирает код, а не модель — никаких «в базе я ничего не нашёл»."""
    q = question.lower()
    if "спасиб" in q or "thank" in q:
        return ("Пожалуйста! Обращайтесь — я всегда тут. Спросите про любую "
                "программу, например: «какой порог инвестиций на Мальте?»")
    return ("Привет! Я ассистент по базе знаний Passportivity о программах "
            "гражданства и ВНЖ. Спросите, например: «какой порог инвестиций "
            "на Мальте?» — или напишите «что ты умеешь».")


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
                 "\nЭто подсказка, а не замена: главный — исходный вопрос сотрудника."
                 "\nЕсли фрагменты расходятся с формулировкой подсказки — отвечай на"
                 " исходный вопрос по фрагментам и не заостряй внимание на расхождении."
                 "\nЯзык ответа — как в исходном вопросе сотрудника.")
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


def _sources_footer(fragments: list[dict], limit: int = 3) -> str:
    """Не больше limit ссылок, в порядке релевантности фрагментов (а не по
    алфавиту): в обзорных ответах источников бывают десятки, простыня из 26
    ссылок бесполезна и вводит в заблуждение. Остальное — строкой «и ещё N»."""
    seen: list[tuple[str, str, str]] = []
    for f in fragments:
        if not f.get("notion_url"):
            continue
        key = (f["country"].strip(), f["program"].strip(), f["notion_url"])
        if key not in seen:
            seen.append(key)
    if not seen:
        return ""
    lines = [f"• <{url}|{country} — {program}>" for country, program, url in seen[:limit]]
    extra = len(seen) - limit
    if extra > 0:
        lines.append(f"• …и ещё {extra} источников в базе знаний")
    return "\n\nИсточники:\n" + "\n".join(lines)


def answer(question: str, fragments: list[dict], history: list[dict],
           resolved: str | None = None) -> str:
    msgs = _merge_history(
        history + [{"role": "user",
                    "text": build_user_message(fragments, question, resolved)}])
    resp = _anthropic().messages.create(
        model=config.ANSWER_MODEL, max_tokens=1600,
        system=_SYSTEM, messages=msgs)
    return _to_mrkdwn(resp.content[0].text) + _sources_footer(fragments)
