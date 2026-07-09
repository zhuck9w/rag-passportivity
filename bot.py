"""Slack-бот (Socket Mode). Слушает упоминания и личку, отвечает в тред."""
import logging
import re
import threading
import time

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient

import config
import db
from answer import answer
from retrieval import retrieve

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kb-bot")

config.require("SLACKBOT_OAUTH", "SLACKBOT_APPLEVEL",
               "ANTHROPIC_API_KEY", "VOYAGE_API_KEY",
               "SUPABASE_URL", "SUPABASE_SECRET_KEY")

app = App(client=WebClient(token=config.SLACKBOT_OAUTH,
                           proxy=config.PROXY or None))
BOT_USER_ID = app.client.auth_test()["user_id"]

_processed: dict[str, float] = {}
_processed_lock = threading.Lock()


def _already_handled(key: str) -> bool:
    """Дедупликация: Slack может прислать событие повторно, а в личке
    упоминание бота приходит и как app_mention, и как message. Обработчики
    работают в разных потоках — поэтому под замком."""
    now = time.time()
    with _processed_lock:
        for k, ts in list(_processed.items()):
            if now - ts > 900:
                _processed.pop(k, None)
        if key in _processed:
            return True
        _processed[key] = now
    return False


def _clean(text: str) -> str:
    return re.sub(rf"<@{BOT_USER_ID}>", "", text or "").strip()


_user_names: dict[str, str] = {}


def _user_name(user_id: str) -> str:
    """Имя пользователя для журнала обращений; кэшируем, чтобы не дёргать
    users.info на каждый вопрос. Любой сбой — просто возвращаем id."""
    if user_id in _user_names:
        return _user_names[user_id]
    name = user_id
    try:
        info = app.client.users_info(user=user_id)["user"]
        profile = info.get("profile") or {}
        name = (profile.get("display_name") or profile.get("real_name")
                or info.get("real_name") or user_id)
    except Exception:
        pass
    _user_names[user_id] = name
    return name


def _to_history(messages: list[dict], skip_ts: str) -> list[dict]:
    history = []
    for msg in messages:
        if msg.get("ts") == skip_ts:
            continue  # текущий вопрос передаётся отдельно, в историю не включаем
        role = "assistant" if (msg.get("bot_id") or msg.get("user") == BOT_USER_ID) else "user"
        text = _clean(msg.get("text", ""))
        if text:
            history.append({"role": role, "text": text})
    return history[-20:]


def _thread_history(channel: str, thread_ts: str, event_ts: str) -> list[dict]:
    """Весь тред с пагинацией: replies отдаёт СТАРЕЙШИЕ сообщения первыми,
    поэтому с limit=20 без пагинации длинный тред терял бы свежий контекст."""
    messages, cursor = [], None
    while True:
        resp = app.client.conversations_replies(channel=channel, ts=thread_ts,
                                                limit=200, cursor=cursor)
        messages += resp["messages"]
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return _to_history(messages, event_ts)


def _dm_history(channel: str, event_ts: str) -> list[dict]:
    """В личке follow-up обычно пишут новым сообщением, а не в тред —
    подтягиваем последние сообщения переписки как контекст."""
    resp = app.client.conversations_history(channel=channel, limit=12)
    return _to_history(list(reversed(resp["messages"])), event_ts)  # старые → новые


def handle_question(event, say) -> None:
    if _already_handled(event.get("client_msg_id") or event["ts"]):
        return
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]
    question = _clean(event.get("text", ""))
    if not question:
        say(text="Задайте вопрос текстом — например: «какой порог инвестиций на Мальте?»",
            thread_ts=thread_ts)
        return

    try:  # ⏳ заработает после добавления scope reactions:write, иначе тихо пропустится
        app.client.reactions_add(channel=channel, timestamp=event["ts"],
                                 name="hourglass_flowing_sand")
    except Exception:
        pass

    try:
        if event.get("thread_ts"):
            history = _thread_history(channel, thread_ts, event["ts"])
        elif event.get("channel_type") == "im":
            history = _dm_history(channel, event["ts"])
        else:
            history = []
        fragments, query, countries, topic = retrieve(question, history)
        log.info("q=%r -> query=%r countries=%r topic=%r fragments=%d",
                 question, query, countries, topic, len(fragments))
        try:
            # Журнал без текста вопроса. Сбой (например, таблицы query_log
            # ещё нет в БД) не должен ломать ответ пользователю.
            user_id = event.get("user", "")
            db.log_query(
                slack_user_id=user_id,
                user_name=_user_name(user_id),
                channel_type=event.get("channel_type") or "channel",
                countries=countries,
                topic=topic,
                found=bool(fragments),
                fragments_count=len(fragments),
            )
        except Exception as e:
            log.warning("не удалось записать журнал обращений: %s", e)
        if not fragments:
            say(text="В базе знаний я ничего не нашёл по этому вопросу. "
                     "Попробуйте переформулировать или указать страну.",
                thread_ts=thread_ts)
            return
        say(text=answer(question, fragments, history), thread_ts=thread_ts)
    except Exception:
        log.exception("ошибка обработки вопроса")
        say(text="Что-то пошло не так. Попробуйте ещё раз через минуту.",
            thread_ts=thread_ts)
    finally:
        try:
            app.client.reactions_remove(channel=channel, timestamp=event["ts"],
                                        name="hourglass_flowing_sand")
        except Exception:
            pass


@app.event("app_mention")
def on_mention(event, say):
    handle_question(event, say)


@app.event("message")
def on_message(event, say):
    if event.get("channel_type") != "im":
        return
    if event.get("subtype") or event.get("bot_id"):
        return
    handle_question(event, say)


if __name__ == "__main__":
    log.info("Бот запускается, подключаюсь к Slack…")
    SocketModeHandler(app, config.SLACKBOT_APPLEVEL,
                      proxy=config.PROXY or None).start()
