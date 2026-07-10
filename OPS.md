# Шпаргалка по эксплуатации бота (VPS)

Все команды выполняются на VPS по SSH. Бот живёт в `/opt/kb-assistant`,
работает как systemd-служба `kb-bot` от пользователя `kbbot`.

---

## Логи

```bash
sudo journalctl -u kb-bot -f              # лог бота В РЕАЛЬНОМ ВРЕМЕНИ (выход: Ctrl+C)
sudo journalctl -u kb-bot -n 50 --no-pager  # последние 50 строк
sudo journalctl -u kb-bot --since "1 hour ago" --no-pager  # за последний час
tail -f /opt/kb-assistant/sync.log        # лог синхронизаций в реальном времени
tail -50 /opt/kb-assistant/sync.log       # последние 50 строк синка
```

Что искать в логе бота:
- `Bolt app is running!` — бот подключился к Slack, всё хорошо;
- `q=... -> query=... countries=... topic=... fragments=N` — обработан вопрос;
- `Traceback` / `ERROR` — ошибка, читать текст ниже неё.

## Управление ботом

```bash
sudo systemctl status kb-bot     # жив ли: ждём active (running)
sudo systemctl restart kb-bot    # перезапустить (после правок .env или git pull)
sudo systemctl stop kb-bot       # остановить (бот замолчит)
sudo systemctl start kb-bot      # запустить снова
```

После перезагрузки сервера ничего делать НЕ нужно: бот стартует сам
(автозапуск включён), cron-расписание тоже живёт само.

## Обновление кода (после наших доработок)

```bash
cd /opt/kb-assistant
sudo -u kbbot git pull
sudo -u kbbot ./.venv/bin/pip install -r requirements.txt   # на случай новых зависимостей
sudo systemctl restart kb-bot
```

## Синхронизация знаний вручную

Обычно не нужна — cron делает это каждый час в :17. Но если поправили Notion
и хочется, чтобы бот узнал сразу:

```bash
cd /opt/kb-assistant
sudo -u kbbot ./.venv/bin/python sync.py            # только изменённые страницы
sudo -u kbbot ./.venv/bin/python sync.py --dry-run  # посмотреть, что изменится
sudo -u kbbot ./.venv/bin/python sync.py --full     # полная переиндексация (редко)
```

## Проверка поиска и ответов без Slack

```bash
cd /opt/kb-assistant
sudo -u kbbot ./.venv/bin/python scripts/ask.py "какой порог инвестиций на Мальте?"
sudo -u kbbot ./.venv/bin/python scripts/ask.py "тот же вопрос" --answer
```

---

## Бот молчит — чек-лист по порядку

1. **Служба жива?** `sudo systemctl status kb-bot`
   - не `active (running)` → `sudo systemctl restart kb-bot`, затем смотреть логи.
2. **Что в логах?** `sudo journalctl -u kb-bot -n 50 --no-pager`
   - ошибки соединения (`ConnectionError`, `ProxyError`, таймауты) → умер прокси, см. пункт 3;
   - `invalid_auth` → проблема с токеном Slack в `.env` (перевыпустили? сравнить с локальным);
   - `В .env не заполнены: ...` → в `.env` пропала переменная, вписать и `restart`.
3. **Прокси жив?** (главный подозреваемый на российском VPS)
   ```bash
   curl -x http://ЛОГИН:ПАРОЛЬ@146.103.117.236:59977 -s -o /dev/null -w "%{http_code}\n" https://api.anthropic.com
   ```
   Трёхзначный код = жив. Ошибка = прокси лежит: чинить прокси или временно
   поднять бота на своём ПК (см. ниже).
4. **Отвечает «В базе знаний я этого не нашёл» на всё подряд?**
   Проверить, что синк работает: `tail -20 /opt/kb-assistant/sync.log` — там
   должны быть свежие запуски без FAIL.
5. **Отвечает «Что-то пошло не так»?** Смотреть лог бота в момент вопроса
   (`journalctl -u kb-bot -f` + задать вопрос) — причина будет в traceback.

## Запасной вариант: временно поднять бота на своём ПК

Если VPS/прокси надолго легли, бот можно запустить локально (на ПК с VPN
прокси не нужен — там `PROXY_ENABLED=false`):

```powershell
cd "C:\Users\tonyt\Desktop\Passportivity\RAG Slack-Notion"
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe bot.py
```

Важно: работать должен ОДИН экземпляр — перед этим останови серверного
(`sudo systemctl stop kb-bot`), а когда VPS оживёт — выключи локального
(Ctrl+C) и запусти серверного обратно (`start`).

## Полная реанимация с нуля

Если сервер переустановили/переехали — весь путь развёртывания описан
в [DEPLOY.md](DEPLOY.md) (9 шагов, ~30 минут). Данные при этом не теряются:
знания и журнал в Supabase, код на GitHub, секреты — из локального `.env`.

---

## Где смотреть данные

- **Чанки базы знаний**: Supabase → Table Editor → `chunks`
  (сколько всего: `select count(*) from chunks;` в SQL Editor).
- **Журнал обращений** (кто/когда/тема): Supabase → Table Editor → `query_log`.
- **Журнал синхронизаций** (когда и какие программы обновились): Table Editor →
  `sync_log`. Пишется только когда что-то реально поменялось; жив ли cron —
  видно по `sync.log` на сервере. Последние изменения (SQL Editor):
  ```sql
  select started_at, mode, updated, failed, deleted, programs
  from sync_log order by id desc limit 10;
  ```
- **Статистика тем за неделю** (SQL Editor):
  ```sql
  select topic, count(*) from query_log
  where asked_at > now() - interval '7 days'
  group by topic order by 2 desc;
  ```
- **По каким вопросам бот ничего не нашёл** (кандидаты на пополнение базы):
  ```sql
  select asked_at, user_name, countries, topic from query_log
  where found = false order by asked_at desc limit 20;
  ```

## Настройки, которые можно крутить (файл config.py)

После любой правки — `git pull` на сервере и `sudo systemctl restart kb-bot`.

| Константа | Что делает | Сейчас |
|---|---|---|
| `ANSWER_MODEL` | модель ответов (качество/цена) | Haiku 4.5; апгрейд → `claude-opus-4-8` |
| `TOP_K` | сколько фрагментов даём модели | 8 |
| `MIN_SIMILARITY` | порог отсечения нерелевантного | 0.54 |
