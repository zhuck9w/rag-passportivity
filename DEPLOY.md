# Деплой на VPS — пошаговая инструкция

Цель: бот работает на сервере 24/7, знания обновляются сами (каждый час + полная
переиндексация в ночь на воскресенье), при сбое процесс перезапускается.

Все команды выполняются на VPS по SSH (кроме шага 3 — он в браузере).
Рассчитано на Ubuntu 22.04+/Debian 12. Подставить нужно только две вещи:
логин-пароль прокси в шаге 1 и содержимое `.env` в шаге 7.

---

## Шаг 0. Проверка сервера

```bash
cat /etc/os-release | head -2      # какая ОС
python3 --version                  # нужен Python 3.10 или новее
```

Если Python старее 3.10 — остановись и сообщи, подберём вариант.

Ставим системные пакеты (git, venv, ротация логов):

```bash
sudo apt update && sudo apt install -y git python3-venv logrotate curl
```

## Шаг 1. Проверка прокси с VPS — критично для российского сервера

Anthropic и Voyage напрямую с российских адресов не работают — весь трафик бота
пойдёт через прокси. Проверяем, что прокси доступен именно С СЕРВЕРА:

```bash
curl -x http://ЛОГИН:ПАРОЛЬ@146.103.117.236:59977 -s -o /dev/null -w "%{http_code}\n" https://api.anthropic.com
```

Ожидание: любой трёхзначный код (403, 404 — неважно) — значит, прокси отвечает
и туннель работает. Если ошибка соединения или `000` — прокси с VPS недоступен:
дальше не идти, разбираемся с прокси.

## Шаг 2. Отдельный пользователь для бота

Бот не должен работать от root. Домашний каталог отделён от каталога кода —
иначе `git clone` упёрся бы в непустую папку:

```bash
sudo useradd -r -m -d /var/lib/kbbot -s /usr/sbin/nologin kbbot
```

(Если ругнётся на `/usr/sbin/nologin` — замени на `/sbin/nologin`.)

## Шаг 3. Деплой-ключ: серверу — только чтение кода

Генерируем ключ и регистрируем его в GitHub как ключ «только на чтение»:

```bash
sudo -u kbbot mkdir -m 700 /var/lib/kbbot/.ssh
sudo -u kbbot ssh-keygen -t ed25519 -N "" -f /var/lib/kbbot/.ssh/id_ed25519
sudo cat /var/lib/kbbot/.ssh/id_ed25519.pub
```

Скопируй строку `ssh-ed25519 AAAA...` из вывода, открой в браузере
**github.com/zhuck9w/rag-passportivity → Settings → Deploy keys → Add deploy key**,
вставь ключ, название любое (например `vps`), галку **Allow write access НЕ ставить**.

Вернись на сервер и добавь GitHub в доверенные хосты:

```bash
sudo -u kbbot sh -c 'ssh-keyscan github.com >> /var/lib/kbbot/.ssh/known_hosts'
```

## Шаг 4. Код на сервер

```bash
sudo install -d -o kbbot -g kbbot /opt/kb-assistant
sudo -u kbbot git clone git@github.com:zhuck9w/rag-passportivity.git /opt/kb-assistant
cd /opt/kb-assistant
```

Ожидание: обычный вывод clone без запроса пароля. Если спрашивает пароль —
деплой-ключ не подхватился, проверь шаг 3.

## Шаг 5. Окружение Python

```bash
sudo -u kbbot python3 -m venv /opt/kb-assistant/.venv
sudo -u kbbot /opt/kb-assistant/.venv/bin/pip install -r /opt/kb-assistant/requirements.txt
```

Займёт минуту-две, в конце — `Successfully installed ...`.

## Шаг 6. Секреты

```bash
sudo -u kbbot nano /opt/kb-assistant/.env
```

Вставь содержимое своего локального `.env` (с ПК) и проверь две строки:

```ini
PROXY=http://ЛОГИН:ПАРОЛЬ@146.103.117.236:59977
PROXY_ENABLED=true        # ← на сервере ОБЯЗАТЕЛЬНО true
```

Сохрани (Ctrl+O, Enter, Ctrl+X) и закрой доступ всем, кроме kbbot:

```bash
sudo chmod 600 /opt/kb-assistant/.env
sudo chown kbbot:kbbot /opt/kb-assistant/.env
```

## Шаг 7. Проверка конвейера ДО установки служб

Сначала синхронизация (Notion + Voyage + Supabase через прокси):

```bash
cd /opt/kb-assistant
sudo -u kbbot ./.venv/bin/python sync.py
```

Ожидание: `Карточек в Notion: 42; обновить: 0; удалить: 0` (или пара «ok …»,
если коллеги что-то правили). Затем полный вопрос-ответ (плюс Claude):

```bash
sudo -u kbbot ./.venv/bin/python scripts/ask.py "какой порог инвестиций на Мальте?" --answer
```

Ожидание: фрагменты с похожестью ~0.6 и связный ответ с цифрами.
Если оба теста прошли — сервер полностью рабочий.

## Шаг 8. Бот как служба (24/7, автозапуск, авторестарт)

```bash
sudo cp deploy/kb-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kb-bot
sudo systemctl status kb-bot --no-pager
```

Ожидание: `active (running)`. Логи бота:

```bash
sudo journalctl -u kb-bot -n 20 --no-pager
```

Ожидание: `Bolt app is running!` без traceback.

**Выключи бота на своём ПК**, если он запущен — работать должен один экземпляр.
Проверь в Slack: вопрос боту → ответ теперь приходит с сервера.

## Шаг 9. Расписание синхронизации и ротация логов

```bash
sudo -u kbbot crontab /opt/kb-assistant/deploy/crontab.txt
sudo -u kbbot crontab -l    # проверка: две строки с sync.py
```

Ротация лога синка (чтобы не рос бесконечно):

```bash
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

Готово. С этого момента: правки в Notion подхватываются в течение часа сами,
бот отвечает круглосуточно, при падении перезапускается за 5 секунд.

---

## Шпаргалка на каждый день

| Что | Команда (на VPS) |
|---|---|
| Статус бота | `sudo systemctl status kb-bot` |
| Логи бота (живые) | `sudo journalctl -u kb-bot -f` |
| Перезапустить бота | `sudo systemctl restart kb-bot` |
| Лог синхронизаций | `tail -50 /opt/kb-assistant/sync.log` |
| Синк прямо сейчас | `cd /opt/kb-assistant && sudo -u kbbot ./.venv/bin/python sync.py` |
| **Обновить код** (после наших правок) | `cd /opt/kb-assistant && sudo -u kbbot git pull && sudo systemctl restart kb-bot` |

Типовые проблемы:
- Бот молчит → `journalctl -u kb-bot -n 50`: если ошибки соединения — проверь
  прокси (шаг 1); если `invalid_auth` — проверь токены в `.env`.
- `git pull` просит пароль → слетел деплой-ключ, повтори шаг 3.
- После правки `.env` — обязательно `sudo systemctl restart kb-bot`.
