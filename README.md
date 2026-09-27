# JAC Parts Bot — Этап 1

Telegram-бот каталога запчастей JAC. Сейчас готово: запуск в Docker, база PostgreSQL,
команда `/start`, выбор языка (🇷🇺 / 🇬🇧 / 🇺🇿), сохранение языка и главное меню.
Каталог, регионы и заказы — на следующих этапах (кнопки пока показывают «скоро появится»).

---

## Что нужно заранее

- Сервер (или компьютер) с **Debian 12** и доступом в интернет.
- Доступ к серверу по SSH под пользователем с правами `sudo`.
- Аккаунт Telegram.

Белый IP и домен **не нужны** — бот сам ходит в Telegram (long polling).

---

## Шаг 1. Получить токен бота

1. В Telegram откройте **@BotFather**.
2. Отправьте `/newbot`.
3. Введите название бота (например, `JAC Parts`).
4. Введите username — должен заканчиваться на `bot` (например, `jac_parts_uz_bot`).
5. BotFather пришлёт токен вида `1234567890:AAH...`. **Это пароль от бота — никому не показывайте.**

## Шаг 2. Узнать свой Telegram ID (для админа)

1. Откройте в Telegram **@userinfobot** и нажмите Start.
2. Он пришлёт число `Id: 123456789` — это ваш ID.

---

## Шаг 3. Установить Docker на Debian

Выполните команды по одной на сервере:

```bash
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

Разрешить своему пользователю работать с Docker без `sudo`:

```bash
sudo usermod -aG docker $USER
```

После этого **выйдите из SSH и зайдите снова**.

Проверка:

```bash
docker --version
docker compose version
docker run --rm hello-world
```

Должно появиться `Hello from Docker!`.

Docker сам включится после перезагрузки сервера (проверить: `sudo systemctl is-enabled docker` → `enabled`).

---

## Шаг 4. Загрузить проект на сервер

**Вариант А — архив.** На своём компьютере:

```bash
scp jac-parts-bot-stage1.zip user@IP_СЕРВЕРА:~
```

На сервере:

```bash
sudo apt install -y unzip
unzip jac-parts-bot-stage1.zip
cd jac-parts-bot
```

**Вариант Б — Git** (если вы положили проект в свой репозиторий):

```bash
git clone https://github.com/ВАШ_АККАУНТ/jac-parts-bot.git
cd jac-parts-bot
```

---

## Шаг 5. Создать файл .env

```bash
cp .env.example .env
nano .env
```

Заполните:

```ini
BOT_TOKEN=1234567890:AAH...ваш_токен
ADMIN_IDS=123456789
POSTGRES_DB=jac_parts
POSTGRES_USER=jac_bot
POSTGRES_PASSWORD=придумайте_длинный_пароль
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
DATABASE_URL=
LOG_LEVEL=INFO
```

- Несколько админов — через запятую: `ADMIN_IDS=123456789,987654321`.
- `DATABASE_URL` оставьте пустым — бот соберёт его сам.
- Пароль БД придумайте без символов `@ : / #` (они ломают адрес подключения). Сгенерировать можно так: `openssl rand -hex 16`.

Сохранить в nano: `Ctrl+O`, `Enter`, выйти: `Ctrl+X`.

Закрыть файл от чужих глаз:

```bash
chmod 600 .env
```

> ⚠️ Файл `.env` уже в `.gitignore` — он никогда не попадёт в Git. Не отправляйте его никому.

---

## Шаг 6. Запуск

```bash
docker compose up -d --build
```

Первый раз займёт 1–3 минуты (скачиваются образы). Что происходит:

1. Запускается PostgreSQL.
2. Когда база готова, запускается контейнер бота.
3. Бот применяет миграции (создаёт таблицу `users`) и начинает принимать сообщения.

Проверить, что оба контейнера работают:

```bash
docker compose ps
```

Ожидаемо: у `postgres` статус `Up (healthy)`, у `bot` — `Up`.

## Шаг 7. Логи

```bash
docker compose logs -f bot
```

Ожидаемый результат:

```
INFO  [alembic.runtime.migration] Running upgrade  -> 0001, create users table
... | INFO | jac_parts_bot | Bot @jac_parts_uz_bot started (long polling). Admins: 1
```

Выйти из просмотра логов — `Ctrl+C` (бот продолжит работать).

## Шаг 8. Проверка в Telegram

1. Откройте своего бота, нажмите **Start** (`/start`).
2. Бот предложит 3 языка → выберите, например, **🇺🇿 O‘zbekcha**.
3. Появится меню `🚗 JAC EHTIYOT QISMLARI` с кнопками на узбекском.
4. Нажмите **🌐 Tilni o‘zgartirish** → **🇬🇧 English** — меню сразу станет английским.
5. Снова отправьте `/start` — бот помнит язык и сразу показывает меню.

---

## Проверка PostgreSQL

Посмотреть пользователей в базе:

```bash
docker compose exec postgres psql -U jac_bot -d jac_parts -c "SELECT telegram_id, first_name, language FROM users;"
```

Вы должны увидеть себя и выбранный язык (`ru` / `en` / `uz`).

Интерактивная консоль базы: `docker compose exec postgres psql -U jac_bot -d jac_parts` (выход — `\q`).

## Миграции

Миграции (изменения структуры базы) применяются **автоматически** при каждом запуске бота.
Вручную:

```bash
docker compose run --rm bot alembic upgrade head   # применить
docker compose run --rm bot alembic current        # текущая версия
```

---

## Остановка / перезапуск

```bash
docker compose down         # остановить (данные в базе сохраняются)
docker compose restart bot  # перезапустить только бота
```

> ❗ Никогда не выполняйте `docker compose down -v` — флаг `-v` **удаляет базу данных**.

Автозапуск после перезагрузки сервера уже настроен (`restart: unless-stopped`). Проверить: `sudo reboot`, подождать минуту, зайти и выполнить `docker compose ps`.

## Обновление кода

Когда получите новую версию (следующий этап):

```bash
cd ~/jac-parts-bot
# замените файлы новыми (git pull или распакуйте архив, НЕ трогая .env)
docker compose up -d --build
docker compose logs -f bot
```

---

## Резервная копия (backup) PostgreSQL

```bash
mkdir -p ~/backups
docker compose exec -T postgres pg_dump -U jac_bot -d jac_parts > ~/backups/jac_parts_$(date +%F_%H-%M).sql
ls -lh ~/backups
```

Автоматический ежедневный backup в 03:00 — выполните `crontab -e` и добавьте строку:

```
0 3 * * * cd ~/jac-parts-bot && docker compose exec -T postgres pg_dump -U jac_bot -d jac_parts > ~/backups/jac_parts_$(date +\%F).sql
```

## Восстановление из backup

```bash
docker compose stop bot
docker compose exec -T postgres psql -U jac_bot -d postgres -c "DROP DATABASE jac_parts;"
docker compose exec -T postgres psql -U jac_bot -d postgres -c "CREATE DATABASE jac_parts;"
docker compose exec -T postgres psql -U jac_bot -d jac_parts < ~/backups/ИМЯ_ФАЙЛА.sql
docker compose start bot
```

---

## Если что-то пошло не так

| Что видите | Причина и решение |
|---|---|
| `RuntimeError: BOT_TOKEN не задан` | Не заполнен `BOT_TOKEN` в `.env`. Заполните и выполните `docker compose up -d`. |
| `TelegramUnauthorizedError` | Неверный токен. Скопируйте заново из @BotFather (без пробелов). |
| `password authentication failed` | Пароль в `.env` поменяли после первого запуска. База запомнила старый. Верните старый пароль. (Если данных ещё нет — `docker compose down -v` и запуск заново.) |
| `TelegramConflictError: terminated by other getUpdates` | Бот с этим токеном запущен где-то ещё (например, на вашем ПК). Остановите вторую копию. |
| `permission denied ... docker.sock` | Не выполнили `usermod -aG docker` или не перезашли в SSH. |
| Бот молчит | `docker compose ps` и `docker compose logs --tail 50 bot` — ошибка будет в логах. |
| `address already in use` | Порты наружу не открываются, так что это обычно не наша проблема — пришлите лог. |

---

## Структура проекта (этап 1)

```
jac-parts-bot/
├── app/
│   ├── main.py                 # точка входа: запуск бота
│   ├── config.py               # чтение .env
│   ├── handlers/
│   │   ├── start.py            # /start, главное меню
│   │   └── language.py         # выбор и смена языка
│   ├── keyboards/
│   │   ├── main.py             # кнопки главного меню
│   │   └── language.py         # кнопки выбора языка
│   ├── middlewares/db.py       # сессия БД + пользователь для каждого сообщения
│   ├── database/
│   │   ├── database.py         # подключение к PostgreSQL
│   │   ├── models.py           # таблица users
│   │   └── repositories/users.py
│   ├── services/localization.py
│   └── locales/ru.json, en.json, uz.json   # все тексты бота
├── migrations/                 # Alembic: изменения структуры базы
├── tests/                      # автотесты
├── Dockerfile, docker-compose.yml
├── .env.example
└── requirements.txt
```

**Как поменять текст кнопки или сообщения:** откройте `app/locales/ru.json` (или `en`/`uz`),
измените текст справа от двоеточия, затем `docker compose up -d --build`.

## Запуск тестов (необязательно)

```bash
docker compose run --rm --user root bot sh -c "pip install -q -r requirements-dev.txt && pytest -q"
```

Ожидаемо: `9 passed`.
