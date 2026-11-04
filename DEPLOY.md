# Деплой на VPS — пошаговая инструкция

Цель: бот работает на сервере 24/7, знания обновляются сами (каждый час + полная
переиндексация в ночь на воскресенье), при сбое процесс перезапускается.

**Наш сервер (с ноября 2026):** `185.185.50.174`, Нидерланды, Ubuntu 26.04.
Вход: `ssh -p 1022 dev@185.185.50.174`, затем `sudo -i`. Все команды ниже — под
root (строка ввода кончается на `#`), кроме шага 3, он в браузере.

- На этом же сервере работает кабинет Telegram Outreach (пользователь `outreach`,
  Docker, nginx) — его инструкция в `B2B Outreach\Telegram Outreach\DEPLOY.md`.
  Шаги ниже его не трогают. RAG-бот живёт отдельно: пользователь `kbbot`, папка
  `/opt/kb-assistant`, служба `kb-bot`.
- **Прокси боту здесь не нужен:** из Нидерландов Anthropic, Voyage, Notion, Slack и
  Supabase открываются напрямую (проверено 04.11.2026), в `.env` — `PROXY_ENABLED=false`.
- **База знаний — в Supabase, не на сервере.** Переустановка бота в ней ничего не
  теряет и не требует переиндексации.
- Прежний сервер (`otklix.ru`, Beget) стёрт при взломе хостинга 02.11.2026.

---

## Шаг 1. Системные пакеты

```bash
apt-get update && NEEDRESTART_SUSPEND=1 apt-get -o DPkg::Lock::Timeout=600 install -y --no-install-recommends git python3-venv logrotate cron curl && python3 --version && systemctl is-enabled cron
```

В конце — `Python 3.14…` и `enabled`. `NEEDRESTART_SUSPEND=1` обязателен: без него
Ubuntu после установки может сама перезапустить Docker и nginx кабинета.

## Шаг 2. Отдельный пользователь для бота

Бот не должен работать от root. Домашний каталог отделён от каталога кода —
иначе `git clone` упёрся бы в непустую папку:

```bash
useradd -r -m -d /var/lib/kbbot -s /usr/sbin/nologin kbbot
```

## Шаг 3. Деплой-ключ: серверу — только чтение кода

```bash
sudo -u kbbot mkdir -m 700 /var/lib/kbbot/.ssh
sudo -u kbbot ssh-keygen -t ed25519 -N "" -C kb-bot-nl -f /var/lib/kbbot/.ssh/id_ed25519
cat /var/lib/kbbot/.ssh/id_ed25519.pub
```

Скопируй строку `ssh-ed25519 AAAA… kb-bot-nl`, открой
**github.com/zhuck9w/rag-passportivity → Settings → Deploy keys → Add deploy key**,
название `vps-nl`, вставь ключ, галку **Allow write access НЕ ставить** →
**Add key**. Это открытая половина ключа, она не секрет.

Затем на сервере добавь GitHub в доверенные хосты:

```bash
sudo -u kbbot sh -c 'ssh-keyscan github.com >> /var/lib/kbbot/.ssh/known_hosts'
```

## Шаг 4. Код на сервер

```bash
install -d -o kbbot -g kbbot /opt/kb-assistant
sudo -u kbbot git clone git@github.com:zhuck9w/rag-passportivity.git /opt/kb-assistant
```

Ожидание: обычный вывод clone без запроса пароля. Если спрашивает пароль или пишет
`Permission denied (publickey)` — ключ из шага 3 не добавлен в GitHub.

## Шаг 5. Окружение Python

`constraints.txt` — точные версии библиотек, на которых проходят тесты: без него pip
взял бы самые свежие, и новая версия могла бы молча сломать бота.

```bash
sudo -u kbbot python3 -m venv /opt/kb-assistant/.venv
sudo -u kbbot /opt/kb-assistant/.venv/bin/pip install -r /opt/kb-assistant/requirements.txt -c /opt/kb-assistant/constraints.txt
cd /opt/kb-assistant && sudo -u kbbot ./.venv/bin/python -m pytest -q -p no:cacheprovider
```

Займёт пару минут. В конце — `Successfully installed …` и `100 passed`.

## Шаг 6. Секреты

Создай пустой файл, закрытый от всех, кроме `kbbot`, и открой его:

```bash
install -m 600 -o kbbot -g kbbot /dev/null /opt/kb-assistant/.env
nano /opt/kb-assistant/.env
```

На ПК в VS Code открой `.env` в папке `RAG Slack-Notion` → Ctrl+A, Ctrl+C → в
терминале сервера правый клик (если спросит про несколько строк — «Вставить всё
равно»). Сохрани: Ctrl+O, Enter, Ctrl+X. Проверь — команда покажет только названия
строк, без значений:

```bash
grep -oE '^[A-Z0-9_]+=' /opt/kb-assistant/.env | tr '\n' ' '; echo; grep '^PROXY_ENABLED=' /opt/kb-assistant/.env; ls -l /opt/kb-assistant/.env
```

Среди названий должны быть `NOTION_TOKEN= NOTION_KB_PAGE_ID= VOYAGE_API_KEY=
ANTHROPIC_API_KEY= SUPABASE_URL= SUPABASE_SECRET=` (или `SUPABASE_SECRET_KEY=`)
`SLACKBOT_OAUTH= SLACKBOT_APPLEVEL=`. Вторая строка — `PROXY_ENABLED=false`; если там
`true`, открой файл ещё раз и поменяй на `false`. Третья начинается с `-rw-------`
и содержит `kbbot kbbot`.

## Шаг 7. Проверка конвейера ДО установки службы

Сначала синхронизация (Notion → Voyage → Supabase):

```bash
cd /opt/kb-assistant && sudo -u kbbot ./.venv/bin/python sync.py
```

Ожидание: `Карточек в Notion: …; обновить: …; удалить: 0` и строки `ok …` по
обновлённым страницам (синк не шёл со 2 ноября — несколько страниц могут обновиться).
Затем полный вопрос-ответ (плюс Claude):

```bash
cd /opt/kb-assistant && sudo -u kbbot ./.venv/bin/python scripts/ask.py "какой порог инвестиций на Мальте?" --answer
```

Ожидание: фрагменты с похожестью ~0.6 и связный ответ с цифрами. Если оба теста
прошли — сервер полностью рабочий.

## Шаг 8. Бот как служба (24/7, автозапуск, авторестарт)

**Сначала убедись, что бот не запущен на ПК** (окно с `bot.py`): работать должен один
экземпляр, иначе на каждый вопрос в Slack придут два ответа.

```bash
cp /opt/kb-assistant/deploy/kb-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now kb-bot
sleep 5; systemctl status kb-bot --no-pager | head -n 5; journalctl -u kb-bot -n 20 --no-pager
```

Ожидание: `active (running)` и в логах `Bolt app is running!` без traceback.
Проверь в Slack: вопрос боту → ответ.

## Шаг 9. Расписание синхронизации и ротация логов

```bash
sudo -u kbbot crontab /opt/kb-assistant/deploy/crontab.txt
sudo -u kbbot crontab -l    # проверка: две строки с sync.py
```

Ротация лога синка (чтобы не рос бесконечно):

```bash
tee /etc/logrotate.d/kb-sync >/dev/null <<'EOF'
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

Готово. С этого момента: правки в Notion подхватываются в течение часа сами,
бот отвечает круглосуточно, при падении перезапускается за 5 секунд.

---

## Шпаргалка на каждый день

| Что | Команда (на VPS, под root) |
|---|---|
| Статус бота | `systemctl status kb-bot` |
| Логи бота (живые) | `journalctl -u kb-bot -f` |
| Перезапустить бота | `systemctl restart kb-bot` |
| Лог синхронизаций | `tail -50 /opt/kb-assistant/sync.log` |
| Синк прямо сейчас | `cd /opt/kb-assistant && sudo -u kbbot ./.venv/bin/python sync.py` |
| **Обновить код** (после наших правок) | `cd /opt/kb-assistant && sudo -u kbbot git pull && sudo -u kbbot ./.venv/bin/pip install -q -r requirements.txt -c constraints.txt && systemctl restart kb-bot` |

Типовые проблемы:
- Бот молчит → `journalctl -u kb-bot -n 50`: если `invalid_auth` — проверь токены в
  `.env`; если ошибки соединения — см. OPS.md, «Бот молчит».
- `git pull` пишет `Permission denied (publickey)` → слетел деплой-ключ, повтори шаг 3.
- После правки `.env` — обязательно `systemctl restart kb-bot`.
- Если когда-нибудь понадобится прокси (сервер переедет в Россию и т.п.): в `.env`
  `PROXY=http://логин:пароль@адрес:порт` и `PROXY_ENABLED=true`, затем `restart`.
