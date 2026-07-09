import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_KB_PAGE_ID = os.getenv("NOTION_KB_PAGE_ID", "")
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "") or os.getenv("SUPABASE_SECRET", "")
SLACKBOT_OAUTH = os.getenv("SLACKBOT_OAUTH", "")
SLACKBOT_APPLEVEL = os.getenv("SLACKBOT_APPLEVEL", "")

EMBED_MODEL = "voyage-3.5"
EMBED_DIM = 1024
ANSWER_MODEL = "claude-haiku-4-5-20251001"  # обкатка; не хватит точности — "claude-opus-4-8"
REWRITE_MODEL = "claude-haiku-4-5-20251001"

CHUNK_MAX_CHARS = 2000      # ~1-3 абзаца
CHUNK_MIN_CHARS = 200       # мельче — приклеиваем к соседнему куску того же раздела
CHUNK_OVERLAP_CHARS = 200   # перехлёст между чанками
TOP_K = 8                   # сколько фрагментов отдаём Claude
MIN_SIMILARITY = 0.25       # порог отсечения нерелевантного; калибруется в Task 7 Step 7

# Имена свойств в базах Notion — подтверждены discover.py (Task 2, 2026-07-09).
# Во всех 4 базах ([DC] Caribbean/European/Other/African) имена одинаковые:
# Country — select в 3 базах, multi_select в Caribbean (наш _prop_text умеет оба);
# дубликаты 'Country 1'/'Status 1' в отдельных базах игнорируем.
COUNTRY_PROP = "Country"
STATUS_PROP = "Status"      # тип status, значения вида "Actual"
OWNER_PROP = "Assign"       # тип people; имена приходят (capability есть), "" = не использовать


def require(*names: str) -> None:
    missing = [n for n in names if not globals().get(n)]
    if missing:
        raise SystemExit("В .env не заполнены: " + ", ".join(missing))
