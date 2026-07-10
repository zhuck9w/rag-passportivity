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

-- Журнал обращений к боту. Приватность: сырой текст вопроса и
-- переформулированный запрос НЕ сохраняются — только метаданные.
create table if not exists query_log (
  id bigint generated always as identity primary key,
  asked_at timestamptz not null default now(),
  slack_user_id text not null default '',
  user_name text not null default '',
  channel_type text not null default '',   -- im / channel / mpim
  countries text not null default '',      -- например "Malta, Portugal"
  topic text not null default '',          -- тематика из фиксированного списка
  found boolean not null default true,     -- нашлись ли фрагменты
  fragments int not null default 0
);
alter table query_log enable row level security;

-- Журнал запусков синхронизации: когда обновлялись знания и сколько.
create table if not exists sync_log (
  id bigint generated always as identity primary key,
  started_at timestamptz not null,
  finished_at timestamptz not null default now(),
  mode text not null default '',          -- incremental / full
  cards_total int not null default 0,     -- карточек на доске Notion
  updated int not null default 0,         -- страниц переиндексировано успешно
  failed int not null default 0,          -- страниц с ошибкой (повторятся в след. запуске)
  deleted int not null default 0,         -- страниц удалено из индекса
  chunks_written int not null default 0,  -- чанков записано за прогон
  programs text not null default ''       -- какие программы поменялись ("; "-список)
);
alter table sync_log enable row level security;
