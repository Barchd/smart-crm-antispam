# Локальная разработка

## Требования

- Python 3.14
- pip, venv
- `openssl` (для curl-примеров с HMAC)
- Ollama (опционально, для AI-анализа)

## Установка

```bash
git clone <repo-url>
cd <project>

python3.14 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env
```

Минимум в `.env`:
```env
DJANGO_SECRET_KEY=   # см. ниже
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
CRM_BASE_URL=http://127.0.0.1:8000
```

Сгенерировать все локальные секреты:
```bash
python manage.py generate_tokens
# Скопируй DJANGO_SECRET_KEY, WEBHOOK_SECRET, ADMIN_API_TOKEN в .env
```

## База данных и начальные данные

```bash
python manage.py migrate
python manage.py seed_users     # создаёт head + 2 managers; сохрани пароли из вывода
python manage.py seed_demo      # опционально: демо-клиенты и сделки
```

## Запуск (два терминала)

```bash
# Терминал 1: Django-сервер
python manage.py runserver

# Терминал 2: воркер заявок
python manage.py process_inbound
```

## Адреса

| URL | Описание |
|-----|----------|
| http://127.0.0.1:8000/deals/ | CRM главная |
| http://127.0.0.1:8000/requests/ | Admin Ops (head only) |
| http://127.0.0.1:8000/lead/ | Mock-форма заявки |
| http://127.0.0.1:8000/api/v1/docs | OpenAPI |
| http://127.0.0.1:8000/settings/ai/ | AI provider (head) |
| http://127.0.0.1:8000/settings/bot/ | Telegram (head) |
| http://127.0.0.1:8000/settings/webhook/ | Webhook secret (head) |

## AI (Ollama)

```bash
# macOS
brew install ollama && ollama pull qwen3.5:9b && ollama serve

# Добавь в .env:
# AI_PROVIDER=ollama
# OLLAMA_URL=http://127.0.0.1:11434
# OLLAMA_MODEL=qwen3.5:9b
```

Без AI-провайдера воркер создаёт сделки с `created_without_ai=True` после 3 неудачных попыток.

## Telegram chat-bot (опционально)

```bash
# Терминал 3
python manage.py run_admin_bot
```

Token и allowlist вводятся в CRM UI → `/settings/bot/` после логина.

## Тесты

```bash
python manage.py test
python manage.py makemigrations --check --dry-run
```

Подробнее: [testing.md](testing.md)

## Демо-заявки

```bash
python manage.py send_demo_leads --process --fast-retry --max-steps 40
```
