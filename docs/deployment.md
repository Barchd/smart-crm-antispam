# Deployment

## Варианты

| Способ | Когда использовать |
|--------|-------------------|
| [Локальная разработка](development.md) | Dev, отладка |
| Docker (этот файл) | Demo, staging, prod-like |

---

## Docker: быстрый старт

### 1. Подготовь `.env`

```bash
cp .env.example .env
```

Обязательно заполни (см. [environment.md](environment.md)):
```env
DJANGO_SECRET_KEY=   # python manage.py generate_tokens
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
CRM_BASE_URL=http://localhost:8000
WEBHOOK_SECRET=      # python manage.py generate_tokens
ADMIN_API_TOKEN=     # python manage.py generate_tokens
```

### 2. Сборка и запуск

```bash
docker compose up --build -d
```

### 3. Миграции и начальные данные

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_users   # сохрани пароли из вывода
# опционально — демо-данные:
docker compose exec web python manage.py seed_demo
```

### 4. Открой браузер

[http://localhost:8000/](http://localhost:8000/)

---

## Сервисы

| Сервис | Команда | Описание |
|--------|---------|----------|
| `web` | `runserver 0.0.0.0:8000` | Django-сервер |
| `worker` | `process_inbound` | Воркер: rules + AI-обработка заявок |
| `bot` _(opt.)_ | `run_admin_bot` | Telegram customer chat-bot |
| `ollama` _(opt.)_ | image: ollama/ollama | Локальная AI (profile: ollama) |

---

## AI

По умолчанию `AI_PROVIDER=ollama`. Если Ollama запущен **на хосте**:
```env
OLLAMA_URL=http://host.docker.internal:11434
OLLAMA_MODEL=qwen3.5:9b
```

Для OpenAI — установи `AI_PROVIDER=openai` в `.env`; ключ вводится в `/settings/ai/` **в браузере** (не в `.env`).

Без AI-провайдера воркер создаёт сделки с `created_without_ai=True` (автоматический fallback после 3 ошибок).

---

## Telegram chat-bot (опционально)

1. Раскомментируй сервис `bot` в `docker-compose.yml`.
2. Войди в CRM как head → `/settings/bot/` → введи Telegram Bot Token и allowlist.
3. `docker compose restart bot`

---

## Обновление

```bash
docker compose down          # НЕ добавляй -v (потеряешь данные)
git pull
docker compose up --build -d
docker compose exec web python manage.py migrate
```

---

## Ограничения SQLite

- Данные в volume `crm_data`. `docker compose down -v` **удаляет данные** — используй `down` без флагов.
- Для production с нагрузкой — замени SQLite на PostgreSQL (требует изменения settings.py и миграций).
- web и worker используют один SQLite-файл: при высокой нагрузке возможны lock contention.
