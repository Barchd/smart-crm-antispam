# Инструкция по установке и запуску

Документ описывает установку Smart-crm-antispam, запуск с локальной моделью Ollama и переключение на OpenAI provider.

## 1. Требования

- Python `3.14`
- SQLite, идет вместе с Python/Django
- `pip`
- `openssl` для генерации HMAC-подписи в curl-примере
- Ollama, если используется локальный AI provider
- Telegram bot token, только если нужно запускать Telegram-чат-бот

Официальные источники:

- Ollama macOS: `https://docs.ollama.com/macos`
- Ollama download: `https://ollama.com/download`
- OpenAI API keys: `https://developers.openai.com/api/reference/overview/`

## 2. Получение проекта

Если проект еще не скачан, клонировать репозиторий:

```bash
git clone <repository-url>
cd <repository-folder>
```

Если архив уже распакован, перейти в папку проекта:

```bash
cd <project-folder>
```

Создать и активировать виртуальное окружение:

```bash
python3.14 -m venv .venv
source .venv/bin/activate
```

Установить зависимости:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Создать локальный `.env`:

```bash
cp .env.example .env
```

## 3. Настройка `.env`

Сгенерировать секреты:

```bash
python manage.py generate_tokens
```

Команда печатает значения для `DJANGO_SECRET_KEY`, `WEBHOOK_SECRET`, `ADMIN_API_TOKEN`. Она не пишет `.env` автоматически и не меняет файлы репозитория.

Заполнить `.env`:

```env
DJANGO_SECRET_KEY=<django-secret>
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost

CRM_HEAD_PASSWORD=head12345
CRM_MANAGER1_PASSWORD=manager12345
CRM_MANAGER2_PASSWORD=manager22345

WEBHOOK_SECRET=<webhook-secret>
ADMIN_API_TOKEN=<admin-api-token>

BOT_TOKEN=
ADMIN_CHAT_ID=
ADMIN_TELEGRAM_IDS=

AI_PROVIDER=ollama
AI_BACKPRESSURE_ENABLED=true
AI_QUEUE_BACKPRESSURE_THRESHOLD=100
AI_RETRY_BACKPRESSURE_THRESHOLD=10
AI_RETRY_BACKPRESSURE_WINDOW_MINUTES=10

OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3.5:9b

OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-5.6-sol
OPENAI_TRANSCRIPTION_MODEL=gpt-transcribe

CRM_BASE_URL=http://127.0.0.1:8000
```

Правила:

- `.env` не коммитить.
- `DJANGO_SECRET_KEY`, `WEBHOOK_SECRET`, `ADMIN_API_TOKEN`, `BOT_TOKEN`, `OPENAI_API_KEY` не хранить в коде.
- При `DJANGO_DEBUG=false` переменные `WEBHOOK_SECRET` и `ADMIN_API_TOKEN` обязательны.
- После `migrate` AI provider удобнее менять через CRM: `/settings/ai/` под пользователем с ролью `head`.

## 4. База данных и демо-данные

Применить миграции:

```bash
python manage.py migrate
```

Создать пользователей:

```bash
python manage.py seed_users
```

Создать демо-клиентов и сделки:

```bash
python manage.py seed_demo
```

Логины из примера `.env`:

```text
head / head12345
manager1 / manager12345
manager2 / manager22345
```

## 5. Запуск CRM

Терминал 1:

```bash
cd <project-folder>
source .venv/bin/activate
python manage.py runserver
```

Адреса:

- CRM: `http://127.0.0.1:8000/deals/`
- Login: `http://127.0.0.1:8000/login/`
- Mock form: `http://127.0.0.1:8000/lead/`
- OpenAPI: `http://127.0.0.1:8000/api/v1/docs`
- Intake API: `POST http://127.0.0.1:8000/api/v1/intake/lead`

## 6. Запуск worker

Терминал 2:

```bash
cd <project-folder>
source .venv/bin/activate
python manage.py process_inbound
```

Worker забирает заявки в статусах `received` и `retry_wait`, вызывает AI provider, создает клиентов и сделки, пишет `ProcessingLog`.

Если очередь или AI retry storm превышают пороги backpressure, worker не вызывает модель и обрабатывает заявку по правилам:

- low/medium-risk: сделка создается с `created_without_ai=True`
- high-risk: заявка остается `suspicious`
- причина пишется в `ProcessingLog`

Разовый запуск для проверки:

```bash
python manage.py process_inbound --once
```

## 7. Установка и запуск Ollama

### macOS

Официальный способ: скачать Ollama с `https://ollama.com/download/mac` или установить приложение по инструкции `https://docs.ollama.com/macos`.

Если используется Homebrew:

```bash
brew install ollama
```

Запустить Ollama:

```bash
ollama serve
```

Если Ollama установлен как приложение, достаточно открыть приложение Ollama.

### Linux

Официальная команда установки:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Запустить сервис:

```bash
ollama serve
```

Или через systemd, если сервис установлен:

```bash
sudo systemctl start ollama
```

### Установка модели

Скачать модель:

```bash
ollama pull qwen3.5:9b
```

Проверить список моделей:

```bash
ollama list
```

Проверить ответ модели:

```bash
ollama run qwen3.5:9b
```

Настройка проекта для Ollama после запуска CRM:

1. Войти под пользователем `head`.
2. Открыть `http://127.0.0.1:8000/settings/ai/`.
3. Выбрать provider `Ollama`.
4. Указать `Ollama URL` и `Ollama model`.
5. Нажать `Сохранить и проверить подключение`.
6. Перезапустить worker, если он уже был запущен.

## 8. Переключение с Ollama на OpenAI

После `python manage.py migrate` переключение делается через CRM, без правки исходного кода:

1. Войти под пользователем с ролью `head`.
2. Открыть `http://127.0.0.1:8000/settings/ai/`.
3. Выбрать provider `OpenAI`.
4. Указать `OpenAI base URL`, обычно `https://api.openai.com/v1`.
5. Указать `OpenAI model`, например `gpt-5.6-sol`. Для экономии можно выбрать `gpt-5.6-terra` или `gpt-5.6-luna`.
6. Ввести `OpenAI API key` в password-поле.
7. Нажать `Сохранить и проверить подключение`.
8. Перезапустить worker, если он уже был запущен.

Важно:

- OpenAI key не хранится в исходном коде и не выводится обратно в HTML.
- В MVP key хранится в БД проекта; `.env` используется только как fallback для первого запуска.
- Не вставлять OpenAI key в README, тесты, curl-команды или `.env.example`.
- В режиме `openai` текст заявки отправляется во внешний API.
- Если нужен private/local режим, использовать provider `ollama`.

## 9. Возврат с OpenAI на Ollama

1. Войти под пользователем `head`.
2. Открыть `http://127.0.0.1:8000/settings/ai/`.
3. Выбрать provider `Ollama`.
4. Проверить `Ollama URL` и `Ollama model`.
5. Нажать `Сохранить и проверить подключение`.
6. Перезапустить worker, если он уже был запущен.

## 10. Запуск Telegram-бота

Создать бота через BotFather.

После `python manage.py migrate` предпочтительный способ настройки:

1. Войти в CRM под пользователем `head`.
2. Открыть `http://127.0.0.1:8000/settings/bot/`.
3. Ввести `Telegram bot token`.
4. Заполнить `Admin chat/user id` и `Allowed Telegram user ids`.
5. Нажать `Сохранить и проверить подключение`.

Fallback до настройки через CRM: заполнить `.env`:

```env
BOT_TOKEN=<botfather-token>
ADMIN_CHAT_ID=<your-telegram-user-id>
ADMIN_TELEGRAM_IDS=<your-telegram-user-id>
CRM_BASE_URL=http://127.0.0.1:8000
```

Запустить:

```bash
python manage.py run_admin_bot
```

После смены token на странице `/settings/bot/` перезапустить процесс бота.

Команды:

```text
/recent
/errors
/stats
/open <request_id>
/retry <request_id>
```

Бот отвечает только пользователям из allowlist и не выводит имя, телефон, email, текст заявки или `ai_summary`.

Если `BOT_TOKEN` утек:

1. Отозвать токен через BotFather.
2. Выпустить новый токен.
3. Обновить `.env`.
4. Если token хранится в CRM, обновить его на `/settings/bot/`.
5. Перезапустить `python manage.py run_admin_bot`.
6. Проверить логи доступа.

## 11. Тестовая отправка заявки через API

Убедиться, что сервер запущен:

```bash
python manage.py runserver
```

В другом терминале:

```bash
cd <project-folder>
source .venv/bin/activate
set -a
source .env
set +a
```

Отправить подписанную заявку:

```bash
body='{"external_id":"manual-1001","source":"site_form","name":"Иван","phone":"+7 (999) 123-45-67","email":"ivan@example.com","text":"Интересует Haval Jolion в кредит","metadata":{"page":"/catalog/haval/jolion"}}'
ts=$(date +%s)
sig=$(printf '%s' "$body" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" -hex | sed 's/^.* //')

curl -i http://127.0.0.1:8000/api/v1/intake/lead \
  -H "Content-Type: application/json" \
  -H "X-Timestamp: $ts" \
  -H "X-Signature: $sig" \
  --data "$body"
```

Ожидаемый результат:

- первый запрос: `202 Accepted`
- повтор с тем же `external_id`: `200 OK`
- в CRM появится заявка
- после работы worker появится клиент и сделка

## 12. Демо-заявки

Отправить 12 демо-заявок через реальные endpoints:

```bash
python manage.py send_demo_leads
```

Отправить и сразу обработать:

```bash
python manage.py send_demo_leads --process --fast-retry --max-steps 40
```

В наборе есть:

- нормальная заявка
- дубль телефона
- дубль `external_id`
- невалидный телефон
- spam links
- prompt injection
- `force_ai_fail`
- `force_error`
- honeypot
- разные источники

## 13. Проверки

```bash
python manage.py check
python manage.py test
python manage.py makemigrations --check --dry-run
```

Проверка секретов в репозитории:

```bash
rg -n "sk-[A-Za-z0-9]{20,}|[0-9]{8,}:[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}" . --glob '!.venv/**' --glob '!.env' --glob '!db.sqlite3'
```

Ожидаемо: команда не должна найти реальные токены.

## 14. Частые проблемы

### `ModuleNotFoundError: No module named 'django'`

Активировать окружение и установить зависимости:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### `RuntimeError: Не задана обязательная переменная окружения DJANGO_SECRET_KEY`

Заполнить `.env` и запускать команды из корня проекта.

### AI уходит в `retry_wait`

Для Ollama:

```bash
ollama list
ollama serve
```

Проверить `.env`:

```env
AI_PROVIDER=ollama
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3.5:9b
```

Для OpenAI:

- открыть `/settings/ai/` под `head`
- проверить, что выбран provider `OpenAI`
- заново ввести API key, если он был очищен
- нажать `Сохранить и проверить подключение`
- убедиться, что worker перезапущен после смены настроек

### AI перегружается при большом потоке заявок

Проверить backpressure-настройки:

```env
AI_BACKPRESSURE_ENABLED=true
AI_QUEUE_BACKPRESSURE_THRESHOLD=100
AI_RETRY_BACKPRESSURE_THRESHOLD=10
AI_RETRY_BACKPRESSURE_WINDOW_MINUTES=10
```

Для более слабого сервера можно уменьшить порог очереди, например:

```env
AI_QUEUE_BACKPRESSURE_THRESHOLD=20
```

После изменения `.env` перезапустить worker.

### Бот не отвечает

Проверить:

- token заполнен на `/settings/bot/` или в fallback `BOT_TOKEN`
- allowlist на `/settings/bot/` или fallback `ADMIN_CHAT_ID` / `ADMIN_TELEGRAM_IDS` содержит numeric Telegram user id
- команда отправлена в private chat
- процесс `python manage.py run_admin_bot` запущен
