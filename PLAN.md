# План внедрения: RAG-ассистент по базе знаний (Notion → Supabase → Claude → Slack)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Цель:** Slack-бот, который отвечает на вопросы сотрудников по базе знаний Passportivity в Notion (страница «Консолидация данных RU»), строго на основе содержимого базы, со ссылками на первоисточник.

**Архитектура:** Два независимых контура. (1) Индексация: `sync.py` по расписанию читает доску Notion (только чтение), режет страницы на чанки с «паспортами» (страна/программа/раздел/статус), векторизует через Voyage AI и складывает в Supabase (pgvector). (2) Ответы: `bot.py` держит Socket Mode-соединение со Slack; на вопрос — переформулировка через Haiku, векторный поиск с фильтром по странам, ответ через Claude строго по найденным фрагментам (на обкатку — Haiku 4.5; апгрейд до Opus — одна константа), публикация в тред с источниками.

**Стек:** Python 3.11+, `notion-client` 2.x, `slack-bolt` (Socket Mode), `supabase`, `anthropic`, `voyageai`, `python-dotenv`, `pytest`. Без LangChain и других фреймворков.

_План прошёл многоагентное ревью (9 независимых проверок: Notion API, Supabase/pgvector, Slack, Anthropic/OpenAI SDK, качество RAG, трассировка кода, трассировка тестов, безопасность/эксплуатация, исполнимость); все 41 замечание учтены в этой версии._

## Глобальные ограничения

- Notion — **строго только чтение**: используются только `databases.query`, `blocks.children.list`, никаких вызовов записи. Токен создан с capability «Read content».
- **`notion-client` только 2.x** (`>=2.3,<3`): в 3.x убрали `databases.query` (перешли на data sources API 2025-09-03) — не обновлять мажорную версию без переписывания `notion_reader.py`.
- Бот отвечает **только по базе знаний**: правило в системном промпте + порог похожести `MIN_SIMILARITY` (нерелевантное отсекается до вызова Claude; при пустой выдаче Claude не вызывается вообще).
- Модели (менять только через `config.py`): ответы — `claude-haiku-4-5-20251001` (решение на обкатку; не хватит точности на приёмке — поднять до `claude-opus-4-8`, это одна константа); переформулировка — `claude-haiku-4-5-20251001`; эмбеддинги — Voyage `voyage-3.5`, размерность **1024**.
- Имена переменных `.env` — ровно как в разделе «Предпосылки» (уже существующие имена сохранены).
- Разработка на Windows (PowerShell), деплой на Linux VPS (systemd + cron). Код кроссплатформенный.
- Секреты живут только в `.env` (в `.gitignore`), в git не попадают никогда. `письмо-IT-директору.md` — внутренняя переписка, в git тоже не коммитим.
- Все клиенты API создаются лениво (при первом вызове), чтобы модули импортировались в тестах без ключей.
- Языки контента: русский + английский вперемешку — всё, от эмбеддингов до промптов, должно это переживать.

## Предпосылки (проверить до Task 0)

1. ✅ `ANTHROPIC_API_KEY` и `VOYAGE_API_KEY` получены (2026-07-09) — вписать в `.env`. `OPENAI_KEY` больше не используется — удалить из `.env`.
2. **`NOTION_KB_PAGE_ID`** — открыть страницу «Консолидация данных RU» → Share → Copy link. ID — 32 hex-символа в конце ссылки (после последнего дефиса названия, без `?v=...`). Записать в `.env`.
3. **Supabase — создаём НОВЫЙ проект** (Task 1), аккаунт годится существующий. Ключи чужого проекта (`SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_URL`, `SECRET`) из этого `.env` **убрать** — они от другой задачи, боту не нужны, и держать лишние секреты на сервере бота нельзя.
4. Целевой вид `.env` (файл лежит в корне проекта):

```ini
NOTION_TOKEN=ntn_...
NOTION_KB_PAGE_ID=<32 hex>
VOYAGE_API_KEY=...
ANTHROPIC_API_KEY=sk-ant-...
SUPABASE_URL=https://<новый-проект>.supabase.co
SUPABASE_SECRET_KEY=sb_secret_...
SLACKBOT_OAUTH=xoxb-...
SLACKBOT_APPLEVEL=xapp-...
```

5. **Проверить настройки Slack-приложения** — api.slack.com/apps → наше приложение: (a) OAuth & Permissions → Bot Token Scopes совпадают со списком в `slack-app-manifest.yaml` (включая `mpim:history` — добавлен для тредов в групповых личках); (b) Event Subscriptions → Subscribe to bot events содержит `app_mention` и `message.im`; (c) Socket Mode включён; (d) Basic Information → App-Level Tokens: токен `xapp-...` имеет scope `connections:write`. После любого изменения scope — «Reinstall to Workspace» и обновить `SLACKBOT_OAUTH` в `.env` (токен мог перевыпуститься).

## Журнал решений

- **Эмбеддинги: Voyage `voyage-3.5` (1024) — финально** (2026-07-09): ключ Voyage заведён, возвращаемся к исходному выбору (мультиязычное качество RU/EN + бесплатная квота). Запасной путь на OpenAI = ключ + 3 константы + `sync.py --full`.
- **Модель ответов: Haiku 4.5 на обкатку** (2026-07-09, решение Антона — дешевле Opus в ~5 раз). Если на приёмке (Task 11) ответы неточны или смешивают программы — поднять `ANSWER_MODEL` до `claude-opus-4-8` (одна константа в `config.py`).
- Supabase: отдельный новый проект ради изоляции секретов и данных от другого проекта.
- Транспорт Slack: Socket Mode (публичный адрес не нужен, обсуждено ранее).
- Реакция-«часики» ⏳ во время обработки: в манифесте нет scope `reactions:write`, поэтому код ставит реакцию в `try/except` — заработает, если позже добавить scope в настройках приложения и переустановить. Не блокер.
- В каналах бот отвечает **только на упоминания** (`message.channels` не подписан — бот не читает переписку каналов). Follow-up в канале требует снова упомянуть бота; в личке — нет.

## Карта файлов

```
RAG Slack-Notion/
├── PLAN.md                  # этот план
├── .env                     # секреты (не в git)
├── .env.example             # имена переменных без значений
├── .gitignore
├── conftest.py              # пустой; даёт pytest видеть модули в корне
├── requirements.txt
├── config.py                # env + все константы и имена свойств Notion
├── notion_reader.py         # Notion → карточки (Card) и markdown страниц
├── chunker.py               # markdown → чанки с паспортами (Chunk)
├── embedder.py              # Voyage: тексты → векторы
├── db.py                    # Supabase: запись/поиск/состояние синхронизации
├── sync.py                  # CLI индексации (--full, --dry-run)
├── discover.py              # разовая разведка структуры доски
├── retrieval.py             # переформулировка вопроса + поиск
├── answer.py                # сборка промпта + вызов Claude
├── bot.py                   # Slack-бот (Socket Mode)
├── prompts/
│   ├── system.txt           # правила поведения ассистента
│   └── rewrite.txt          # промпт переформулировки вопроса
├── sql/schema.sql           # таблицы, индексы, match_chunks, list_countries
├── scripts/
│   ├── check_db.py          # смоук-тест embedder+db
│   └── ask.py               # консольная проверка поиска и ответов
├── tests/
│   ├── test_notion_md.py
│   ├── test_chunker.py
│   ├── test_retrieval.py
│   └── test_answer.py
└── deploy/
    ├── kb-bot.service       # systemd-юнит для VPS
    └── crontab.txt          # cron: часовой sync + недельный --full
```

Поток данных: `notion_reader.list_cards()` → `Card` → `notion_reader.fetch_page_markdown()` → `chunker.chunk_page()` → `Chunk[]` → `embedder.embed_texts()` → `db.replace_page_chunks()`. Ответ: `bot.py` → `retrieval.retrieve()` (внутри: `rewrite` → `embed_query` → `db.search` + порог похожести) → `answer.answer()` → Slack.

---

### Task 0: Скелет проекта, git, конфиг

**Files:**
- Create: `.gitignore`, `.env.example`, `conftest.py`, `requirements.txt`, `config.py`

**Interfaces:**
- Produces: модуль `config` — переменные окружения как строки-константы (`NOTION_TOKEN`, `NOTION_KB_PAGE_ID`, `OPENAI_KEY`, `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SLACKBOT_OAUTH`, `SLACKBOT_APPLEVEL`), константы моделей/чанков/поиска и функция `require(*names)` — падает с понятной ошибкой, если переменная пустая.

- [x] **Step 1: git и окружение** (PowerShell, из папки проекта)

```powershell
git init
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Если `Activate.ps1` падает с «running scripts is disabled on this system» — один раз выполнить и повторить активацию:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

- [x] **Step 2: `.gitignore`**

```gitignore
.env
.venv/
__pycache__/
*.pyc
.pytest_cache/
sync.log
письмо-IT-директору.md
```

- [x] **Step 3: `requirements.txt` и установка**

```text
# notion-client 3.x перешёл на API 2025-09-03 (data sources) и убрал
# databases.query — не поднимать мажорную версию без переписывания notion_reader.py
notion-client>=2.3,<3
slack-bolt>=1.20
supabase>=2.6
anthropic>=0.40
voyageai>=0.3
python-dotenv>=1.0
pytest>=8.0
```

```powershell
pip install -r requirements.txt
```

- [x] **Step 4: `.env.example`** — скопировать блок «Целевой вид `.env`» из предпосылок, заменив значения на пустые. Привести реальный `.env` к этому набору имён (убрать чужие ключи Supabase и ненужный больше `OPENAI_KEY`; добавить `NOTION_KB_PAGE_ID`, `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`).

- [x] **Step 5: `conftest.py`** в корне проекта:

```python
# Намеренно пустой. Наличие conftest.py в корне заставляет pytest добавить
# корень проекта в sys.path — иначе тесты из tests/ не найдут модули
# (chunker, config и т.д.) и упадут с ModuleNotFoundError.
```

- [x] **Step 6: `config.py`**

```python
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_KB_PAGE_ID = os.getenv("NOTION_KB_PAGE_ID", "")
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "")
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

# Имена свойств в базах Notion — уточняются в Task 2 (discover.py):
COUNTRY_PROP = "Страна"
STATUS_PROP = "Статус"
OWNER_PROP = ""             # "" = не использовать


def require(*names: str) -> None:
    missing = [n for n in names if not globals().get(n)]
    if missing:
        raise SystemExit("В .env не заполнены: " + ", ".join(missing))
```

- [x] **Step 7: Проверка**

Run: `python -c "import config; print('ok', config.EMBED_DIM)"`
Expected: `ok 1024`

Run: `python -c "import config; config.require('SUPABASE_URL')"`
Expected (до Task 1 переменная пуста): `В .env не заполнены: SUPABASE_URL`

- [x] **Step 8: Commit**

```powershell
git add .gitignore .env.example conftest.py requirements.txt config.py PLAN.md slack-app-manifest.yaml
git commit -m "chore: project skeleton, config, dependencies"
```

---

### Task 1: Новый проект Supabase и схема БД

**Files:**
- Create: `sql/schema.sql`

**Interfaces:**
- Produces: таблицы `chunks`, `sync_state`; SQL-функции `match_chunks(query_embedding vector(1024), match_count int, filter_country text)` → строки с полями `id, page_id, country, program, section, status, notion_url, page_edited_at, content, similarity` и `list_countries()` → список стран.

- [x] **Step 1: Создать проект** — supabase.com → New project (в существующем аккаунте): имя `kb-assistant`, регион EU (Frankfurt), сгенерировать пароль БД и сохранить его в менеджер паролей. Бесплатный тариф допускает два активных проекта — второй как раз наш.

- [x] **Step 2: Ключи в `.env`** — Project Settings → API: скопировать `Project URL` → `SUPABASE_URL`; секретный ключ (`sb_secret_...`; в старом интерфейсе — `service_role`) → `SUPABASE_SECRET_KEY`.

- [x] **Step 3: `sql/schema.sql`**

```sql
create extension if not exists vector;

create table if not exists chunks (
  id bigint generated always as identity primary key,
  page_id text not null,
  country text not null default '',
  program text not null default '',
  section text not null default '',
  status text not null default '',
  owners text not null default '',
  notion_url text not null default '',
  page_edited_at text not null default '',   -- ISO-строка из Notion как есть
  chunk_index int not null default 0,
  content text not null,
  embedding vector(1024)
);

create index if not exists chunks_page_id_idx on chunks (page_id);
create index if not exists chunks_country_idx on chunks (country);
create index if not exists chunks_embedding_idx
  on chunks using hnsw (embedding vector_cosine_ops);

-- какая версия страницы уже проиндексирована (сравниваем строки как есть,
-- чтобы не ловить расхождения форматов дат)
create table if not exists sync_state (
  page_id text primary key,
  last_edited text not null
);

-- RLS включаем без политик: публичные ключи не читают ничего,
-- наш секретный ключ RLS обходит
alter table chunks enable row level security;
alter table sync_state enable row level security;

-- ef_search=100: при фильтре по стране HNSW-скан должен набрать достаточно
-- кандидатов ДО фильтра, иначе может вернуть меньше match_count строк
create or replace function match_chunks(
  query_embedding vector(1024),
  match_count int default 8,
  filter_country text default null
)
returns table (
  id bigint, page_id text, country text, program text, section text,
  status text, notion_url text, page_edited_at text,
  content text, similarity float
)
language sql stable
set hnsw.ef_search = 100
as $$
  select c.id, c.page_id, c.country, c.program, c.section,
         c.status, c.notion_url, c.page_edited_at, c.content,
         1 - (c.embedding <=> query_embedding) as similarity
  from chunks c
  where filter_country is null or c.country = filter_country
  order by c.embedding <=> query_embedding
  limit match_count;
$$;

-- список стран считаем на сервере: выборка всей таблицы через API
-- обрезается на 1000 строках и молча теряла бы страны
create or replace function list_countries()
returns table (country text)
language sql stable as $$
  select distinct c.country
  from chunks c
  where c.country <> ''
  order by 1;
$$;
```

- [x] **Step 4: Применить схему** — Supabase Dashboard → SQL Editor → вставить содержимое `sql/schema.sql` → Run.
Expected: `Success. No rows returned`.

- [x] **Step 5: Проверка** — там же выполнить:

```sql
select count(*) from chunks;
select * from list_countries();
```
Expected: `0` и пустой список (таблица и функции есть).

- [x] **Step 6: Commit**

```powershell
git add sql/schema.sql
git commit -m "feat: supabase schema with pgvector, match_chunks and list_countries"
```

---

### Task 2: Разведка структуры доски Notion

**Files:**
- Create: `discover.py`
- Modify: `config.py` (значения `COUNTRY_PROP`, `STATUS_PROP`, `OWNER_PROP`)

**Interfaces:**
- Consumes: `config.NOTION_TOKEN`, `config.NOTION_KB_PAGE_ID`
- Produces: подтверждённые имена свойств карточек в `config.py`. Ничего программного — скрипт разовый.

- [x] **Step 1: `discover.py`**

```python
"""Разовая разведка: какие базы лежат на странице и какие у карточек свойства.
Читает и печатает — ничего не меняет. Ищет базы рекурсивно: в Notion их
часто кладут внутрь колонок или тогглов."""
from notion_client import Client
import config

config.require("NOTION_TOKEN", "NOTION_KB_PAGE_ID")
notion = Client(auth=config.NOTION_TOKEN)


def find_databases(block_id: str, found: list) -> None:
    cursor = None
    while True:
        resp = notion.blocks.children.list(block_id=block_id, start_cursor=cursor)
        for b in resp["results"]:
            if b["type"] == "child_database":
                found.append((b["id"], b["child_database"].get("title", "")))
            elif b.get("has_children") and b["type"] != "child_page":
                find_databases(b["id"], found)  # базы бывают в колонках и тогглах
        cursor = resp.get("next_cursor")
        if not cursor:
            return


def main() -> None:
    dbs: list = []
    find_databases(config.NOTION_KB_PAGE_ID, dbs)
    print(f"Баз данных на странице: {len(dbs)}")
    for db_id, title in dbs:
        resp = notion.databases.query(database_id=db_id, page_size=2)
        pages = resp["results"]
        print(f"\n=== {title} — карточек в первой выборке: {len(pages)} ===")
        if pages:
            for name, prop in pages[0]["properties"].items():
                print(f"  свойство: {name!r}  тип: {prop['type']}")
            print("  пример карточки:", pages[0]["url"])


if __name__ == "__main__":
    main()
```

- [x] **Step 2: Запустить**

Run: `python discover.py`
Expected: список баз («[DC] Caribbean countries and islands», «[DC] European countries», …) и для каждой — имена свойств с типами. Если скрипт падает с `object_not_found` — интеграция не подключена к странице: вернуться к IT-директору (меню «⋯» страницы → Connections).

- [x] **Step 3: Зафиксировать имена свойств в `config.py`** — по выводу: свойство со страной (тип `select` или `status`) → `COUNTRY_PROP`; статус актуальности (`Actual`/`Need update`, тип `status` или `select`) → `STATUS_PROP`; ответственные (тип `people`) → `OWNER_PROP` (или оставить `""`).
Два предупреждения:
  - Если у интеграции только capability «Read content», свойство `people` вернёт пользователей без имён (только id) и `owners` будет всегда пустым. Либо оставить `OWNER_PROP = ""`, либо попросить IT включить у интеграции capability «Read user information (without email)» — это по-прежнему не даёт прав на запись.
  - Если свойства-страны нет вообще (страна видна только как колонка доски) — записать `COUNTRY_PROP = ""` и сообщить в чат: группировка доски недоступна через API, обсудим запасной вариант (например, страна из названия базы).

- [x] **Step 4: Commit**

```powershell
git add discover.py config.py
git commit -m "feat: notion board discovery script, property names pinned"
```

---

### Task 3: Чтение Notion → markdown

**Files:**
- Create: `notion_reader.py`
- Test: `tests/test_notion_md.py`

**Interfaces:**
- Consumes: `config` (токен, id страницы, имена свойств)
- Produces: `@dataclass Card(page_id: str, program: str, country: str, status: str, owners: str, url: str, last_edited: str)`; `list_cards() -> list[Card]`; `fetch_page_markdown(page_id: str) -> str`; чистые функции `_rich(rt_list) -> str`, `_block_lines(block, depth=0) -> list[str]`.

- [x] **Step 1: Написать падающий тест `tests/test_notion_md.py`**

```python
from notion_reader import _rich, _block_lines


def test_rich_text_with_link():
    rt = [{"plain_text": "сайт", "href": "https://x"},
          {"plain_text": " и текст", "href": None}]
    assert _rich(rt) == "[сайт](https://x) и текст"


def test_heading_renders_as_markdown():
    b = {"id": "1", "type": "heading_2", "has_children": False,
         "heading_2": {"rich_text": [{"plain_text": "Требования", "href": None}]}}
    assert _block_lines(b) == ["## Требования"]


def test_bulleted_item():
    b = {"id": "2", "type": "bulleted_list_item", "has_children": False,
         "bulleted_list_item": {"rich_text": [{"plain_text": "пункт", "href": None}]}}
    assert _block_lines(b) == ["- пункт"]


def test_unknown_block_skipped():
    b = {"id": "3", "type": "image", "has_children": False, "image": {}}
    assert _block_lines(b) == []
```

- [x] **Step 2: Убедиться, что тест падает**

Run: `pytest tests/test_notion_md.py -q`
Expected: FAIL / ошибка импорта `notion_reader`.

- [x] **Step 3: Реализация `notion_reader.py`**

```python
"""Чтение базы знаний из Notion. Только чтение: databases.query и
blocks.children.list, никаких вызовов записи."""
import time
from dataclasses import dataclass

from notion_client import Client
from notion_client.errors import HTTPResponseError, RequestTimeoutError

import config

_client = None


def notion() -> Client:
    global _client
    if _client is None:
        config.require("NOTION_TOKEN")
        _client = Client(auth=config.NOTION_TOKEN)
    return _client


def notion_call(fn, **kwargs):
    """Вызов API с повтором при rate limit (3 rps), таймаутах и сбоях 5xx.
    HTTPResponseError ловит и APIResponseError (это её подкласс), и «сырые»
    502/503 от шлюзов, у которых тело ответа не в формате Notion."""
    for attempt in range(5):
        try:
            return fn(**kwargs)
        except RequestTimeoutError:
            if attempt == 4:
                raise
            time.sleep(1.5 * (attempt + 1))
        except HTTPResponseError as e:
            if e.status not in (429, 500, 502, 503, 504) or attempt == 4:
                raise
            retry_after = float(e.headers.get("retry-after") or 0)
            time.sleep(max(retry_after, 1.5 * (attempt + 1)))


@dataclass
class Card:
    page_id: str
    program: str
    country: str
    status: str
    owners: str
    url: str
    last_edited: str


def _prop_text(prop: dict) -> str:
    t = prop.get("type", "")
    v = prop.get(t)
    if not v:
        return ""
    if t in ("title", "rich_text"):
        return "".join(rt.get("plain_text", "") for rt in v)
    if t in ("select", "status"):
        return v.get("name", "")
    if t == "multi_select":
        return ", ".join(o.get("name", "") for o in v)
    if t == "people":
        return ", ".join(p.get("name", "") for p in v if p.get("name"))
    if t == "date":
        return v.get("start", "") or ""
    return ""


def _title_of(props: dict) -> str:
    for prop in props.values():
        if prop.get("type") == "title":
            return _prop_text(prop)
    return ""


def list_databases() -> list[str]:
    """Ищем child_database рекурсивно: базы бывают внутри колонок и тогглов."""
    config.require("NOTION_KB_PAGE_ID")
    ids: list[str] = []

    def scan(block_id: str) -> None:
        for b in _children(block_id):
            if b["type"] == "child_database":
                ids.append(b["id"])
            elif b.get("has_children") and b["type"] != "child_page":
                scan(b["id"])

    scan(config.NOTION_KB_PAGE_ID)
    return ids


def list_cards() -> list[Card]:
    cards = []
    for db_id in list_databases():
        cursor = None
        while True:
            resp = notion_call(notion().databases.query,
                               database_id=db_id, start_cursor=cursor, page_size=100)
            for page in resp["results"]:
                props = page["properties"]
                cards.append(Card(
                    page_id=page["id"],
                    program=_title_of(props),
                    country=_prop_text(props.get(config.COUNTRY_PROP, {})),
                    status=_prop_text(props.get(config.STATUS_PROP, {})),
                    owners=_prop_text(props.get(config.OWNER_PROP, {})) if config.OWNER_PROP else "",
                    url=page["url"],
                    last_edited=page["last_edited_time"],
                ))
            cursor = resp.get("next_cursor")
            if not cursor:
                break
    return cards


def _children(block_id: str) -> list[dict]:
    out, cursor = [], None
    while True:
        resp = notion_call(notion().blocks.children.list,
                           block_id=block_id, start_cursor=cursor)
        out += resp["results"]
        cursor = resp.get("next_cursor")
        if not cursor:
            return out


_LIST_TYPES = ("bulleted_list_item", "numbered_list_item", "toggle", "to_do")


def _rich(rt_list: list[dict]) -> str:
    out = []
    for rt in rt_list:
        text = rt.get("plain_text", "")
        href = rt.get("href")
        out.append(f"[{text}]({href})" if href else text)
    return "".join(out)


def _block_lines(block: dict, depth: int = 0) -> list[str]:
    t = block["type"]
    d = block.get(t, {})
    pad = "  " * depth
    lines: list[str] = []
    handled_children = False

    if t == "paragraph":
        text = _rich(d.get("rich_text", []))
        if text.strip():
            lines.append(pad + text)
    elif t == "heading_1":
        lines.append("# " + _rich(d.get("rich_text", [])))
    elif t == "heading_2":
        lines.append("## " + _rich(d.get("rich_text", [])))
    elif t == "heading_3":
        lines.append("### " + _rich(d.get("rich_text", [])))
    elif t in ("bulleted_list_item", "toggle"):
        lines.append(pad + "- " + _rich(d.get("rich_text", [])))
    elif t == "numbered_list_item":
        lines.append(pad + "1. " + _rich(d.get("rich_text", [])))
    elif t == "to_do":
        mark = "x" if d.get("checked") else " "
        lines.append(f"{pad}- [{mark}] " + _rich(d.get("rich_text", [])))
    elif t in ("callout", "quote"):
        lines.append(pad + "> " + _rich(d.get("rich_text", [])))
    elif t == "code":
        lines.append("```")
        lines.append(_rich(d.get("rich_text", [])))
        lines.append("```")
    elif t == "divider":
        lines.append("---")
    elif t == "table":
        rows = [r for r in _children(block["id"]) if r["type"] == "table_row"]
        cells = [[_rich(c) for c in r["table_row"].get("cells", [])] for r in rows]
        if cells:
            lines.append("| " + " | ".join(cells[0]) + " |")
            lines.append("|" + "---|" * len(cells[0]))
            for row in cells[1:]:
                lines.append("| " + " | ".join(row) + " |")
        handled_children = True
    elif t in ("child_page", "child_database"):
        handled_children = True  # вложенные страницы не разворачиваем
    # image, file, embed, bookmark и прочее — пропускаем молча

    if block.get("has_children") and not handled_children:
        child_depth = depth + 1 if t in _LIST_TYPES else depth
        for child in _children(block["id"]):
            lines += _block_lines(child, child_depth)
    return lines


def fetch_page_markdown(page_id: str) -> str:
    lines: list[str] = []
    for block in _children(page_id):
        lines += _block_lines(block)
    return "\n".join(lines)
```

- [x] **Step 4: Тесты зелёные**

Run: `pytest tests/test_notion_md.py -q`
Expected: `4 passed`

- [x] **Step 5: Живой смоук — одна страница целиком**

Run: `python -c "import notion_reader as nr; cards = nr.list_cards(); print(len(cards), 'карточек'); c = cards[0]; print(c.country, '|', c.program, '|', c.status); print(nr.fetch_page_markdown(c.page_id)[:800])"`
Expected: число карточек (порядка десятков), метаданные первой и первые ~800 символов её текста. Открыть эту страницу в Notion и глазами сверить, что текст совпадает и ничего важного не потеряно (таблицы, списки).

- [x] **Step 6: Commit**

```powershell
git add notion_reader.py tests/test_notion_md.py
git commit -m "feat: notion reader - cards and page markdown"
```

---

### Task 4: Нарезка на чанки с паспортами

**Files:**
- Create: `chunker.py`
- Test: `tests/test_chunker.py`

**Interfaces:**
- Consumes: `notion_reader.Card`, константы `config.CHUNK_*`
- Produces: `@dataclass Chunk(content: str, section: str, index: int)`; `chunk_page(card: Card, markdown: str) -> list[Chunk]`; чистые функции `build_passport(country, program, section, status, edited_date) -> str`, `split_sections(md) -> list[tuple[str, str]]`, `split_long(text, max_chars, overlap) -> list[str]`.

- [x] **Step 1: Падающие тесты `tests/test_chunker.py`**

```python
from chunker import build_passport, split_sections, split_long, chunk_page
from notion_reader import Card

CARD = Card(page_id="p1", program="Golden Visa", country="Мальта",
            status="Actual", owners="", url="https://notion.so/x",
            last_edited="2026-02-19T16:49:00.000Z")


def test_passport_format():
    p = build_passport("Мальта", "Golden Visa", "Требования", "Actual", "2026-02-19")
    assert p == "[Мальта — Golden Visa | Раздел: Требования | Статус: Actual, обновлено 2026-02-19]"


def test_passport_without_optional_parts():
    assert build_passport("", "Golden Visa", "", "", "") == "[Golden Visa]"


def test_split_sections():
    md = "вступление\n## Требования\nтекст а\n## Сроки\nтекст б"
    assert [s[0] for s in split_sections(md)] == ["", "Требования", "Сроки"]


def test_split_long_overlap():
    text = "\n".join(f"строка {i} " + "х" * 90 for i in range(40))
    parts = split_long(text, max_chars=1000, overlap=200)
    assert len(parts) > 1
    assert all(len(p) <= 1400 for p in parts)
    assert parts[1].splitlines()[0] in parts[0]  # перехлёст: начало II есть в I


def test_overlap_with_long_paragraphs():
    # юниты длиннее overlap: перехлёст всё равно должен существовать
    text = "\n".join("абзац " + "х" * 400 for _ in range(10))
    parts = split_long(text, max_chars=1000, overlap=200)
    assert len(parts) > 1
    assert parts[1][:100] in parts[0]


def test_small_table_stays_whole():
    rows = "\n".join("| ячейка | ячейка |" for _ in range(5))
    parts = split_long("до\n" + rows + "\nпосле", max_chars=2000, overlap=50)
    assert len(parts) == 1


def test_big_table_split_repeats_header():
    header = "| Страна | Сумма |\n|---|---|"
    rows = "\n".join(f"| строка {i} | {i} евро |" for i in range(60))
    parts = split_long(header + "\n" + rows, max_chars=400, overlap=50)
    assert len(parts) > 1
    assert all(p.splitlines()[0] == "| Страна | Сумма |" for p in parts)


def test_chunk_page_passports_everywhere():
    md = "## Требования\n" + "т" * 3000
    chunks = chunk_page(CARD, md)
    assert len(chunks) >= 2
    assert all(c.content.startswith("[Мальта — Golden Visa") for c in chunks)
    assert all(c.section == "Требования" for c in chunks)
```

- [x] **Step 2: Убедиться, что падают**

Run: `pytest tests/test_chunker.py -q`
Expected: FAIL (нет модуля `chunker`).

- [x] **Step 3: Реализация `chunker.py`**

```python
"""Markdown страницы → чанки. Каждый чанк начинается с «паспорта»:
[Страна — Программа | Раздел: ... | Статус: ..., обновлено ...] —
это главный механизм, не дающий перепутать похожие программы."""
from dataclasses import dataclass

import config
from notion_reader import Card


@dataclass
class Chunk:
    content: str
    section: str
    index: int


def build_passport(country: str, program: str, section: str,
                   status: str, edited_date: str) -> str:
    parts = [f"{country} — {program}" if country else program]
    if section:
        parts.append(f"Раздел: {section}")
    if status:
        parts.append(f"Статус: {status}" +
                     (f", обновлено {edited_date}" if edited_date else ""))
    return "[" + " | ".join(parts) + "]"


def split_sections(markdown: str) -> list[tuple[str, str]]:
    """Режем по заголовкам #/##/### → [(название раздела, текст), ...]."""
    sections: list[tuple[str, str]] = []
    title, buf = "", []
    for line in markdown.splitlines():
        if line.startswith("#"):
            if "\n".join(buf).strip():
                sections.append((title, "\n".join(buf).strip()))
            title, buf = line.lstrip("#").strip(), []
        else:
            buf.append(line)
    if "\n".join(buf).strip():
        sections.append((title, "\n".join(buf).strip()))
    return sections


def _units(text: str) -> list[str]:
    """Строки текста; подряд идущие строки таблицы — один блок."""
    units, table = [], []
    for line in text.splitlines():
        if line.lstrip().startswith("|"):
            table.append(line)
        else:
            if table:
                units.append("\n".join(table))
                table = []
            if line.strip():
                units.append(line)
    if table:
        units.append("\n".join(table))
    return units


def _split_table(table: str, max_chars: int) -> list[str]:
    """Огромную таблицу режем по строкам, повторяя шапку в каждом куске:
    иначе хвост таблицы не влезет в лимит эмбеддинга и станет ненаходимым."""
    lines = table.splitlines()
    if len(table) <= max_chars or len(lines) < 4:
        return [table]
    header = lines[:2]  # строка шапки + разделитель |---|
    header_size = sum(len(line) + 1 for line in header)
    pieces, cur, size = [], list(header), header_size
    for row in lines[2:]:
        if size + len(row) > max_chars and len(cur) > 2:
            pieces.append("\n".join(cur))
            cur, size = list(header), header_size
        cur.append(row)
        size += len(row) + 1
    pieces.append("\n".join(cur))
    return pieces


def _hard_split(unit: str, max_chars: int, overlap: int) -> list[str]:
    """Строку длиннее max_chars (абзац без переносов) режем жёстко,
    с посимвольным перехлёстом."""
    step = max(max_chars - overlap, 1)
    return [unit[i:i + max_chars] for i in range(0, len(unit), step)]


def split_long(text: str, max_chars: int, overlap: int) -> list[str]:
    units: list[str] = []
    for u in _units(text):
        if u.lstrip().startswith("|"):
            units += _split_table(u, max_chars)
        elif len(u) > max_chars:
            units += _hard_split(u, max_chars, overlap)
        else:
            units.append(u)

    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for u in units:
        if size + len(u) > max_chars and buf:
            chunks.append("\n".join(buf))
            tail, tail_size = [], 0
            for prev in reversed(buf):
                if tail_size + len(prev) > overlap:
                    break
                tail.insert(0, prev)
                tail_size += len(prev)
            if not tail and not buf[-1].lstrip().startswith("|"):
                # последний юнит длиннее overlap — берём его хвост посимвольно
                # (после кусков таблиц перехлёст не нужен: у них своя шапка)
                tail = [buf[-1][-overlap:]]
                tail_size = len(tail[0])
            buf, size = tail, tail_size
        buf.append(u)
        size += len(u)
    if buf:
        chunks.append("\n".join(buf))
    return chunks


def chunk_page(card: Card, markdown: str) -> list[Chunk]:
    date = card.last_edited[:10] if card.last_edited else ""
    result: list[Chunk] = []
    for title, text in split_sections(markdown) or [("", markdown)]:
        for piece in split_long(text, config.CHUNK_MAX_CHARS, config.CHUNK_OVERLAP_CHARS):
            if (len(piece.strip()) < config.CHUNK_MIN_CHARS
                    and result and result[-1].section == title):
                # мелочь клеим к предыдущему куску ТОГО ЖЕ раздела:
                # чужой паспорт не должен врать про раздел
                result[-1].content += "\n" + piece
                continue
            passport = build_passport(card.country, card.program, title,
                                      card.status, date)
            result.append(Chunk(content=passport + "\n" + piece,
                                section=title, index=len(result)))
    return result
```

- [x] **Step 4: Тесты зелёные**

Run: `pytest tests/test_chunker.py -q`
Expected: `8 passed`

- [x] **Step 5: Смоук на реальной странице**

Run: `python -c "import notion_reader as nr; from chunker import chunk_page; c = nr.list_cards()[0]; ch = chunk_page(c, nr.fetch_page_markdown(c.page_id)); print(len(ch), 'чанков'); print(ch[0].content[:300])"`
Expected: несколько чанков, первый начинается с паспорта с реальной страной и программой.

- [x] **Step 6: Commit**

```powershell
git add chunker.py tests/test_chunker.py
git commit -m "feat: chunker with passports, section split, table-aware overlap"
```

---

### Task 5: Эмбеддинги и слой БД

**Files:**
- Create: `embedder.py`, `db.py`, `scripts/check_db.py`

**Interfaces:**
- Consumes: `config`, `chunker.Chunk`, `notion_reader.Card`, функции `match_chunks` и `list_countries` из Task 1
- Produces: `embed_texts(texts: list[str]) -> list[list[float]]`; `embed_query(text: str) -> list[float]`; `db.get_sync_state() -> dict[str, str]`; `db.replace_page_chunks(card, chunks, embeddings) -> None`; `db.delete_pages(page_ids: list[str]) -> None`; `db.list_countries() -> list[str]`; `db.search(embedding, country: str | None = None, k: int = config.TOP_K) -> list[dict]` (dict с ключами из `match_chunks`, включая `similarity`).

- [x] **Step 1: `embedder.py`**

```python
"""Тексты → векторы (Voyage AI voyage-3.5, 1024 числа). input_type различает
документы и запросы — модель дообучена под это, поиск от этого точнее."""
import voyageai

import config

_client = None


def _voyage() -> voyageai.Client:
    global _client
    if _client is None:
        config.require("VOYAGE_API_KEY")
        _client = voyageai.Client(api_key=config.VOYAGE_API_KEY)
    return _client


def _embed(texts: list[str], input_type: str) -> list[list[float]]:
    vectors: list[list[float]] = []
    for i in range(0, len(texts), 100):  # лимит Voyage — 128 текстов на запрос
        resp = _voyage().embed(texts[i:i + 100], model=config.EMBED_MODEL,
                               input_type=input_type)  # truncation включён по умолчанию
        vectors += resp.embeddings
    return vectors


def embed_texts(texts: list[str]) -> list[list[float]]:
    return _embed(texts, "document")


def embed_query(text: str) -> list[float]:
    return _embed([text], "query")[0]
```

- [x] **Step 2: `db.py`**

```python
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
```

- [x] **Step 3: Смоук-скрипт `scripts/check_db.py`**

```python
"""Проверка связки embedder + db: вставить тестовый чанк, найти, удалить."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
import db
from chunker import Chunk
from embedder import embed_texts
from notion_reader import Card

config.require("SUPABASE_URL", "SUPABASE_SECRET_KEY", "VOYAGE_API_KEY")

text = "[Тест — Smoke | Раздел: Проверка] тестовая запись для проверки поиска"
[vec] = embed_texts([text])
print("размер вектора:", len(vec))
assert len(vec) == config.EMBED_DIM

card = Card(page_id="smoke-test", program="Smoke", country="Тест", status="Actual",
            owners="", url="", last_edited="2026-01-01T00:00:00.000Z")
db.replace_page_chunks(card, [Chunk(content=text, section="Проверка", index=0)], [vec])

hits = db.search(vec, country="Тест", k=1)
assert hits and hits[0]["page_id"] == "smoke-test"
print("найдено:", hits[0]["content"][:50], "| similarity:", round(hits[0]["similarity"], 3))
assert "Тест" in db.list_countries()

db.delete_pages(["smoke-test"])
assert db.search(vec, country="Тест", k=1) == []
print("удалено. всё работает")
```

- [x] **Step 4: Запустить смоук**

Run: `python scripts/check_db.py`
Expected:
```
размер вектора: 1024
найдено: [Тест — Smoke | Раздел: Проверка] тестовая запи | similarity: 1.0
удалено. всё работает
```
(similarity может быть 0.999… — это нормально.)

- [x] **Step 5: Commit**

```powershell
git add embedder.py db.py scripts/check_db.py
git commit -m "feat: voyage embeddings and supabase persistence layer"
```

---

### Task 6: Синхронизация Notion → Supabase

**Files:**
- Create: `sync.py`

**Interfaces:**
- Consumes: всё из Task 3–5
- Produces: CLI `python sync.py [--full] [--dry-run]`; инкрементальность через `sync_state`; удаление чанков исчезнувших карточек; ошибка на одной странице не прерывает остальные.

- [x] **Step 1: `sync.py`**

```python
"""Индексация базы знаний: Notion → чанки → векторы → Supabase.
Запускается вручную или по расписанию (cron). Инкрементальная:
перечитывает только страницы, у которых изменился last_edited_time.
(Notion округляет last_edited_time до минуты — правка в ту же минуту,
что и предыдущая, может проскочить; страховка — недельный --full в cron.)"""
import argparse

import config
import db
import notion_reader as nr
from chunker import chunk_page
from embedder import embed_texts


def run(full: bool, dry: bool) -> None:
    config.require("NOTION_TOKEN", "NOTION_KB_PAGE_ID", "VOYAGE_API_KEY",
                   "SUPABASE_URL", "SUPABASE_SECRET_KEY")
    cards = nr.list_cards()
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
    for c in changed:
        try:
            markdown = nr.fetch_page_markdown(c.page_id)
            chunks = chunk_page(c, markdown)
            embeddings = embed_texts([ch.content for ch in chunks])
            db.replace_page_chunks(c, chunks, embeddings)
            print(f"  ok {c.country} — {c.program}: {len(chunks)} чанков")
        except Exception as e:  # одна плохая страница не срывает весь прогон
            failed += 1
            print(f"  FAIL {c.country} — {c.program}: {e}")

    if gone:
        db.delete_pages(gone)
        print(f"Удалены исчезнувшие страницы: {len(gone)}")
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
```

- [x] **Step 2: Сухой прогон**

Run: `python sync.py --dry-run`
Expected: `Карточек в Notion: N; обновить: N; удалить: 0` и список всех карточек (первый запуск — всё «новое»).

- [x] **Step 3: Полная индексация**

Run: `python sync.py --full`
Expected: строка `ok <страна> — <программа>: K чанков` на каждую карточку, `FAIL` — ни одной. Займёт несколько минут (лимит Notion ~3 запроса/сек).

- [x] **Step 4: Проверить содержимое** — в Supabase SQL Editor:

```sql
select country, count(*) as chunks from chunks group by country order by 2 desc;
select content from chunks limit 3;
```
Expected: страны с доски и осмысленные тексты с паспортами.

- [x] **Step 5: Проверить инкрементальность**

Run: `python sync.py`
Expected: `обновить: 0; удалить: 0` — повторный запуск ничего не перерабатывает.

- [x] **Step 6: Commit**

```powershell
git add sync.py
git commit -m "feat: incremental notion-to-supabase sync with per-page error isolation"
```

---

### Task 7: Переформулировка вопроса и поиск

⚠ С этого таска используется `ANTHROPIC_API_KEY` (уже в `.env`).

**Files:**
- Create: `retrieval.py`, `prompts/rewrite.txt`, `scripts/ask.py`
- Test: `tests/test_retrieval.py`

**Interfaces:**
- Consumes: `db.search`, `db.list_countries`, `embedder.embed_query`, `config.MIN_SIMILARITY`
- Produces: `retrieve(question: str, history: list[dict]) -> tuple[list[dict], str, str | None]` — (фрагменты, переформулированный запрос, страна-фильтр если она одна, иначе None). `history` — список `{"role": "user"|"assistant", "text": str}`. Чистая функция `parse_rewrite(raw: str, fallback_query: str, known_countries: list[str]) -> tuple[str, list[str], list[str]]` — (запрос, распознанные страны из базы, упомянутые страны НЕ из базы).

- [x] **Step 1: Падающие тесты `tests/test_retrieval.py`**

```python
from retrieval import parse_rewrite

COUNTRIES = ["Мальта", "Португалия"]


def test_parse_ok_and_country_case_insensitive():
    raw = 'Вот JSON: {"query": "порог инвестиций Мальта", "countries": ["мальта"]}'
    q, matched, unknown = parse_rewrite(raw, "исходный", COUNTRIES)
    assert q == "порог инвестиций Мальта"
    assert matched == ["Мальта"] and unknown == []


def test_parse_two_countries():
    raw = '{"query": "сравнение порогов", "countries": ["Мальта", "Португалия"]}'
    q, matched, unknown = parse_rewrite(raw, "и", COUNTRIES)
    assert matched == ["Мальта", "Португалия"] and unknown == []


def test_parse_empty_countries():
    q, matched, unknown = parse_rewrite('{"query": "все программы", "countries": []}', "и", COUNTRIES)
    assert matched == [] and unknown == []


def test_parse_garbage_falls_back():
    q, matched, unknown = parse_rewrite("не смогу помочь", "исходный вопрос", COUNTRIES)
    assert (q, matched, unknown) == ("исходный вопрос", [], [])


def test_parse_unknown_country_reported():
    q, matched, unknown = parse_rewrite('{"query": "q", "countries": ["Атлантида"]}', "и", COUNTRIES)
    assert matched == [] and unknown == ["Атлантида"]
```

- [x] **Step 2: Убедиться, что падают**

Run: `pytest tests/test_retrieval.py -q`
Expected: FAIL (нет модуля `retrieval`).

- [x] **Step 3: `prompts/rewrite.txt`**

```text
Ты готовишь поисковый запрос для бота базы знаний компании по программам
гражданства и ВНЖ.

Известные страны базы: [[COUNTRIES]]

История диалога (может быть пустой):
[[HISTORY]]

Новый вопрос сотрудника: [[QUESTION]]

Сделай три вещи:
1. Переформулируй вопрос так, чтобы он был полным и понятным без истории:
   подставь страну и программу из контекста, если в вопросе их нет.
2. Перечисли ВСЕ страны, о которых спрашивают. Названия из списка известных
   стран возвращай ТОЧНО как в списке. Если вопрос без привязки к стране —
   верни пустой список. Если спрашивают про страну, которой НЕТ в списке —
   всё равно включи её название, как написал сотрудник.
3. Сам поисковый запрос в "query" формулируй по-русски (база знаний в
   основном на русском), даже если вопрос задан по-английски. Английские
   названия программ и аббревиатуры (Golden Visa, D7, NHR) оставляй как есть.

Примеры:
«а в Португалии?» после обсуждения порога инвестиций на Мальте →
{"query": "минимальный порог инвестиций по программе Португалии", "countries": ["Португалия"]}
«где дешевле ВНЖ — Мальта или Португалия?» →
{"query": "стоимость и минимальный порог инвестиций ВНЖ Мальта Португалия", "countries": ["Мальта", "Португалия"]}
«какие есть программы с ВНЖ за инвестиции?» →
{"query": "программы ВНЖ за инвестиции", "countries": []}

Ответь ТОЛЬКО одним JSON без пояснений:
{"query": "полный вопрос", "countries": ["..."]}
```

- [x] **Step 4: Реализация `retrieval.py`**

```python
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
                  known_countries: list[str]) -> tuple[str, list[str], list[str]]:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return fallback_query, [], []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return fallback_query, [], []
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
    return query, matched, unknown


def rewrite_question(question: str, history: list[dict],
                     countries: list[str]) -> tuple[str, list[str], list[str]]:
    prompt = (_REWRITE_TEMPLATE
              .replace("[[COUNTRIES]]", ", ".join(countries))
              .replace("[[HISTORY]]", _fmt_history(history))
              .replace("[[QUESTION]]", question))
    resp = _anthropic().messages.create(
        model=config.REWRITE_MODEL, max_tokens=300,
        messages=[{"role": "user", "content": prompt}])
    return parse_rewrite(resp.content[0].text, question, countries)


def retrieve(question: str, history: list[dict]) -> tuple[list[dict], str, str | None]:
    countries = db.list_countries()
    query, matched, unknown = rewrite_question(question, history, countries)
    if unknown and not matched:
        # спрашивают про страну, которой нет в базе — честное «не нашёл»,
        # Claude не вызываем и не даём ему фрагменты про другие страны
        return [], query, None
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
    return fragments, query, (matched[0] if len(matched) == 1 else None)
```

- [x] **Step 5: Тесты зелёные**

Run: `pytest tests/test_retrieval.py -q`
Expected: `5 passed`

- [x] **Step 6: `scripts/ask.py` — главная проверка качества поиска**

```python
"""Консольная проверка: что достаёт поиск (и, с --answer, полный ответ)."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from retrieval import retrieve

parser = argparse.ArgumentParser()
parser.add_argument("question")
parser.add_argument("--answer", action="store_true", help="сгенерировать полный ответ")
args = parser.parse_args()

config.require("SUPABASE_URL", "SUPABASE_SECRET_KEY", "VOYAGE_API_KEY", "ANTHROPIC_API_KEY")
fragments, query, country = retrieve(args.question, history=[])
print(f"Переформулировано: {query!r}\nСтрана-фильтр: {country}")
for f in fragments:
    print(f"  {f['similarity']:.3f}  {f['content'].splitlines()[0]}")

if args.answer:
    from answer import answer
    print("\n--- Ответ ---")
    print(answer(args.question, fragments, []))
```

- [x] **Step 7: Прогнать 10–20 реальных вопросов** — это точка тюнинга качества всей системы:

Run: `python scripts/ask.py "какой минимальный порог инвестиций на Мальте?"`
Expected: страна-фильтр `Мальта`, в топе — чанки мальтийских программ (видно по паспортам в первой строке).

Прогнать вопросы разных типов: конкретная страна; сравнение двух стран («где дешевле — X или Y?» — фрагменты должны быть по обеим); вопрос по-английски (запрос должен переформулироваться по-русски, фильтр — сработать); аббревиатуры («D7»); страна не из базы («программа Атлантиды» — пустой результат без вызова Claude).
**Калибровка `MIN_SIMILARITY`:** скрипт печатает similarity каждого фрагмента — по 10–20 вопросам посмотреть типичные значения релевантных и нерелевантных попаданий и подобрать порог (начать с 0.2–0.25; не задирать: англоязычный вопрос к русскому тексту даёт похожесть ниже). Если достаются не те чанки — крутить `TOP_K` (8 → 12), `CHUNK_MAX_CHARS` (изменения чанкинга требуют `python sync.py --full`).

- [x] **Step 8: Commit**

```powershell
git add retrieval.py prompts/rewrite.txt scripts/ask.py tests/test_retrieval.py
git commit -m "feat: query rewrite with multi-country filter and similarity threshold"
```

---

### Task 8: Генерация ответа через Claude

**Files:**
- Create: `answer.py`, `prompts/system.txt`
- Test: `tests/test_answer.py`

**Interfaces:**
- Consumes: фрагменты из `retrieval.retrieve` (dict с `content`, `notion_url`, `program`, `country`, `status`)
- Produces: `answer(question: str, fragments: list[dict], history: list[dict]) -> str` — готовый текст для Slack (с источниками); чистые `build_user_message(fragments, question) -> str`, `_merge_history(history) -> list[dict]`.

- [ ] **Step 1: Падающие тесты `tests/test_answer.py`**

```python
from answer import build_user_message, _merge_history


def test_user_message_contains_fragments_and_question():
    frags = [{"content": "[Мальта — GV] порог 300", "notion_url": "https://n/1",
              "program": "GV", "country": "Мальта", "status": "Actual"}]
    msg = build_user_message(frags, "какой порог?")
    assert "порог 300" in msg
    assert "какой порог?" in msg


def test_history_merged_and_alternating():
    h = [{"role": "user", "text": "а"}, {"role": "user", "text": "б"},
         {"role": "assistant", "text": "в"}]
    merged = _merge_history(h)
    assert [m["role"] for m in merged] == ["user", "assistant"]
    assert merged[0]["content"] == "а\nб"


def test_history_cannot_start_with_assistant():
    merged = _merge_history([{"role": "assistant", "text": "привет"}])
    assert merged == []
```

- [ ] **Step 2: Убедиться, что падают**

Run: `pytest tests/test_answer.py -q`
Expected: FAIL (нет модуля `answer`).

- [ ] **Step 3: `prompts/system.txt`**

```text
Ты — внутренний ассистент компании Passportivity по базе знаний о программах
гражданства и ВНЖ разных стран. Сотрудники задают вопросы в Slack. В каждом
сообщении тебе передают фрагменты базы знаний, найденные по вопросу.

Правила:
1. Отвечай ТОЛЬКО на основе переданных фрагментов. Если ответа в них нет —
   честно скажи: «В базе знаний я этого не нашёл» и предложи уточнить вопрос
   или указать страну. Никогда не отвечай из общих знаний и не додумывай.
2. Суммы, сроки, проценты и требования приводи в точности как во фрагментах.
3. Каждый фрагмент начинается со строки-паспорта в квадратных скобках:
   страна, программа, раздел, статус, дата обновления. Если статус
   «Need update» или «In progress» — обязательно предупреди, что данные могут
   быть неактуальны, и назови дату обновления.
4. Если фрагменты про разные страны или программы — не смешивай их условия,
   разделяй ответ по программам.
5. Отвечай на языке вопроса. Кратко и по делу.
6. Форматируй для Slack: *жирный* для ключевых цифр и сумм, короткие абзацы,
   списки через «•». Без заголовков «#» и без markdown-таблиц.
7. Не добавляй список источников в конце — программа добавит его сама.
8. На вопросы не по теме базы знаний вежливо отвечай, что ты ассистент по
   программам компании, и не пытайся помочь с посторонним.
```

- [ ] **Step 4: Реализация `answer.py`**

```python
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
```

- [ ] **Step 5: Тесты зелёные**

Run: `pytest -q`
Expected: все тесты проекта `passed`.

- [ ] **Step 6: Живой смоук полного ответа**

Run: `python scripts/ask.py "какой минимальный порог инвестиций на Мальте?" --answer`
Expected: связный ответ с цифрами из базы и блоком «Источники: • <ссылка|Мальта — …>». Задать также вопрос не из базы («какая погода в Лиссабоне?») — фрагментов не будет вовсе (порог похожести) или ответ будет «в базе знаний этого нет», без выдумок.

- [ ] **Step 7: Commit**

```powershell
git add answer.py prompts/system.txt tests/test_answer.py
git commit -m "feat: claude answering with system rules and sources footer"
```

---

### Task 9: Slack-бот

**Files:**
- Create: `bot.py`

**Interfaces:**
- Consumes: `retrieval.retrieve`, `answer.answer`, `config.SLACKBOT_OAUTH`, `config.SLACKBOT_APPLEVEL`
- Produces: процесс `python bot.py`: отвечает на упоминания в каналах и сообщения в личке, всегда в тред; контекст диалога — история треда, а в личке без треда — последние сообщения переписки.

- [ ] **Step 1: `bot.py`**

```python
"""Slack-бот (Socket Mode). Слушает упоминания и личку, отвечает в тред."""
import logging
import re
import threading
import time

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

import config
from answer import answer
from retrieval import retrieve

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kb-bot")

config.require("SLACKBOT_OAUTH", "SLACKBOT_APPLEVEL",
               "ANTHROPIC_API_KEY", "VOYAGE_API_KEY",
               "SUPABASE_URL", "SUPABASE_SECRET_KEY")

app = App(token=config.SLACKBOT_OAUTH)
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
        fragments, query, country = retrieve(question, history)
        log.info("q=%r -> query=%r country=%r fragments=%d",
                 question, query, country, len(fragments))
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
    SocketModeHandler(app, config.SLACKBOT_APPLEVEL).start()
```

- [ ] **Step 2: Запустить локально**

Run: `python bot.py`
Expected: строка про подключение, процесс не завершается, ошибок нет.

- [ ] **Step 3: Проверка в Slack** (бот работает у тебя на машине):
1. Личка боту: «какой минимальный порог инвестиций на Мальте?» → ответ в треде с цифрами и источниками.
2. Follow-up в личке **обычным сообщением, не в тред**: «а в Португалии?» → контекст понят (история переписки).
3. Follow-up в том же треде → контекст понят.
4. Добавить бота в тестовый канал (`/invite @kb-assistant`), упомянуть с вопросом → ответ в тред. Follow-up в канале — снова с упоминанием (без упоминания бот сообщений в каналах не получает — так задумано).
5. Вопрос не из базы → честное «не нашёл».
6. В логах — строки `q=... -> query=... country=... fragments=N`.

- [ ] **Step 4: Commit**

```powershell
git add bot.py
git commit -m "feat: slack socket-mode bot with thread and dm context"
```

---

### Task 10: Деплой на VPS

**Files:**
- Create: `deploy/kb-bot.service`, `deploy/crontab.txt`

**Interfaces:**
- Produces: бот работает 24/7 как systemd-служба; `sync.py` — по cron каждый час + полная переиндексация раз в неделю.

- [ ] **Step 1: `deploy/kb-bot.service`**

```ini
[Unit]
Description=KB Assistant (Slack bot)
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/opt/kb-assistant
ExecStart=/opt/kb-assistant/.venv/bin/python bot.py
Restart=always
RestartSec=5
User=kbbot

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: `deploy/crontab.txt`**

```text
# синхронизация каждый час в :17; flock не даёт двум sync.py работать одновременно
17 * * * * cd /opt/kb-assistant && flock -n /opt/kb-assistant/sync.lock ./.venv/bin/python sync.py >> sync.log 2>&1
# полная переиндексация раз в неделю — страховка от минутной точности last_edited_time
47 3 * * 0 cd /opt/kb-assistant && flock -n /opt/kb-assistant/sync.lock ./.venv/bin/python sync.py --full >> sync.log 2>&1
```

- [ ] **Step 3: Доставка кода** — создать приватный репозиторий (GitHub) и запушить; это же наш бэкап:

```powershell
git remote add origin <url приватного репозитория>
git push -u origin HEAD
```

- [ ] **Step 4: На VPS** (по SSH):

```bash
# домашний каталог отделён от каталога кода: useradd -m копирует /etc/skel,
# и git clone в непустой /opt/kb-assistant не сработал бы
sudo useradd -r -m -d /var/lib/kbbot -s /usr/sbin/nologin kbbot

# доступ к приватному репозиторию: деплой-ключ ТОЛЬКО на чтение
sudo -u kbbot mkdir -m 700 /var/lib/kbbot/.ssh
sudo -u kbbot ssh-keygen -t ed25519 -N "" -f /var/lib/kbbot/.ssh/id_ed25519
sudo cat /var/lib/kbbot/.ssh/id_ed25519.pub
#   → GitHub → репозиторий → Settings → Deploy keys → Add deploy key,
#     вставить ключ, галку «Allow write access» НЕ ставить
sudo -u kbbot sh -c 'ssh-keyscan github.com >> /var/lib/kbbot/.ssh/known_hosts'

sudo install -d -o kbbot -g kbbot /opt/kb-assistant
sudo -u kbbot git clone git@github.com:<org>/<repo>.git /opt/kb-assistant
cd /opt/kb-assistant
sudo -u kbbot python3 -m venv .venv
sudo -u kbbot .venv/bin/pip install -r requirements.txt
sudo -u kbbot nano .env      # вставить содержимое локального .env
sudo chmod 600 .env && sudo chown kbbot:kbbot .env
sudo cp deploy/kb-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kb-bot
sudo -u kbbot crontab deploy/crontab.txt

# ротация лога синка (иначе при постоянной ошибке файл растёт бесконечно)
sudo tee /etc/logrotate.d/kb-sync >/dev/null <<'EOF'
/opt/kb-assistant/sync.log {
  monthly
  rotate 3
  compress
  missingok
  notifempty
  su kbbot kbbot
  create 640 kbbot kbbot
}
EOF
```

- [ ] **Step 5: Проверки**

Run: `systemctl status kb-bot` → Expected: `active (running)`.
Run: `journalctl -u kb-bot -n 20` → Expected: строка про подключение, без traceback.
Run: `cd /opt/kb-assistant && sudo -u kbbot ./.venv/bin/python sync.py` → Expected: `обновить: 0` (база уже проиндексирована с твоей машины).
В Slack: задать вопрос — ответ приходит уже с VPS (локальный `bot.py` при этом выключен, чтобы не было двух ботов).

- [ ] **Step 6: Commit**

```powershell
git add deploy/
git commit -m "feat: systemd unit, cron with flock and logrotate for vps"
git push
```

---

### Task 11: Приёмка и тюнинг

**Files:** — (правки по результатам — в `config.py` и `prompts/*.txt`)

- [ ] **Step 1: Прогнать приёмочный чек-лист** (в Slack, желательно силами 1–2 коллег):

| # | Проверка | Ожидание |
|---|---|---|
| 1 | Вопрос с конкретной страной | точные цифры из базы + источник |
| 2 | Follow-up: в личке — обычным сообщением; в канале — снова с упоминанием `@kb-assistant` (без упоминания бот сообщения в каналах не получает — это ожидаемо) | контекст понят |
| 3 | Вопрос по программе со статусом Need update | предупреждение о неактуальности |
| 4 | Страна, которой нет в базе | честное «не нашёл», без фрагментов чужих стран |
| 5 | Вопрос не по теме (погода, болтовня) | вежливый отказ |
| 6 | Вопрос на английском | ответ на английском, фильтр по стране сработал |
| 7 | Сравнение двух стран | фрагменты по обеим, условия не перепутаны |
| 8 | Правка страницы в Notion → через час | бот отвечает по-новому (cron отработал) |
| 9 | 5+ вопросов подряд от разных людей | все получили ответы |
| 10 | Ссылки «Источники» кликабельны и ведут на верные страницы | да |

- [ ] **Step 2: Тюнинг по результатам** — крутить в таком порядке: формулировки `prompts/system.txt` (стиль/строгость) → `MIN_SIMILARITY` (отсечение мусора) → `TOP_K` (полнота) → `CHUNK_MAX_CHARS` + `--full` (гранулярность поиска) → `prompts/rewrite.txt` (понимание follow-up).

- [ ] **Step 3: Зафиксировать итог** — коммит финальных настроек, короткое объявление в Slack команде: что умеет бот, как спрашивать, куда жаловаться.

---

## Что сознательно отложено (не делаем сейчас)

- **Гибридный поиск** (вектор + полнотекстовый) — добавить, если точные термины («D7», «Passeport Talent») будут искаться плохо.
- **Кэширование системного промпта** (Anthropic prompt caching) — срежет расходы при росте трафика.
- **Оценочный датасет** (golden questions) и автоматический прогон качества.
- **Уведомления об ошибках** в отдельный Slack-канал.
- **Возврат на OpenAI-эмбеддинги** (если Voyage чем-то не устроит) — ключ + 3 константы + `sync.py --full`.
- **Апгрейд модели ответов до Opus 4.8** — одна константа `ANSWER_MODEL`, если Haiku не потянет точность на приёмке.
- **Атомарная замена чанков** одной SQL-транзакцией (сейчас: insert новых → delete старых, окно без данных исключено; полная атомарность на нашем масштабе не нужна).
