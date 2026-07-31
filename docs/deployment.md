# Deployment

## Варианты

| Способ | Когда использовать |
|--------|-------------------|
| [Локальная разработка](development.md) | Dev, отладка |
| Docker (этот файл) | Demo, staging, prod-like |

Полный список переменных: [environment.md](environment.md). Локальный Python-путь: [INSTALL.md](../INSTALL.md).

---

## Docker: быстрый старт

### 1. Подготовь `.env`

```bash
cp .env.example .env
```

Минимальный набор (как в `.env.example`):

```env
DJANGO_SECRET_KEY=          # см. генерацию ниже
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
CRM_BASE_URL=http://127.0.0.1:8000
```

При `DJANGO_DEBUG=false` также задай (иначе webhook/admin API не заработают в prod-режиме):

```env
WEBHOOK_SECRET=
ADMIN_API_TOKEN=
```

**Секреты без локального Python** (рекомендуется для Docker):

```bash
# вставь значения в .env
DJANGO_SECRET_KEY=$(openssl rand -hex 32)
WEBHOOK_SECRET=$(openssl rand -hex 32)
ADMIN_API_TOKEN=$(openssl rand -hex 32)
```

Либо сначала подними контейнеры и сгенерируй внутри образа:

```bash
docker compose up --build -d
docker compose exec web python manage.py generate_tokens
# скопируй вывод в .env на хосте, затем:
docker compose up -d --force-recreate
```

**Доступ не только с localhost** (сервер по IP/домену, например `194.135.33.204`):

```env
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,194.135.33.204
CRM_BASE_URL=http://194.135.33.204:8000
```

Иначе Django ответит `DisallowedHost`.

AI / Telegram / webhook-секрет удобнее задавать в UI после старта: `/settings/ai|bot|webhook/` (head). Не клади `OPENAI_API_KEY` и `BOT_TOKEN` в `.env`, если пользуешься UI.

### 2. Сборка и запуск

```bash
docker compose up --build -d
```

### 3. Миграции и seed

```bash
docker compose exec web python manage.py migrate
```

Пользователи и демо — **выбери один вариант**:

```bash
# вариант A — только пользователи (пароли из ЭТОГО вывода):
docker compose exec web python manage.py seed_users

# вариант B — демо-данные (внутри снова вызывает seed_users;
# пароли из ПЕРВОГО seed_users станут недействительными —
# смотри пароли в выводе seed_demo):
docker compose exec web python manage.py seed_demo
```

Чтобы пароли не «плавали» между запусками, задай в `.env`:

```env
CRM_HEAD_PASSWORD=...
CRM_MANAGER1_PASSWORD=...
CRM_MANAGER2_PASSWORD=...
```

Итоговые логины всегда из **последнего** вывода `seed_users` / `seed_demo`.

### 4. Открой браузер

- Локально: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- На сервере: `http://ВАШ_IP:8000/` (и хост в `DJANGO_ALLOWED_HOSTS`)

---

## Сервисы

| Сервис | Команда | Описание |
|--------|---------|----------|
| `web` | `runserver 0.0.0.0:8000` | Django-сервер |
| `worker` | `process_inbound` | Воркер: rules + AI-обработка заявок |
| `bot` _(opt.)_ | `run_admin_bot` | Telegram customer chat-bot |
| `ollama` _(opt.)_ | image: ollama/ollama | Локальная AI (profile: ollama) |

Ollama **не** скачивается при обычном `docker compose up` — сервис закомментирован.

---

## AI

По умолчанию в настройках приложения может быть Ollama. Если Ollama на **хосте**, а CRM в Docker:

```env
OLLAMA_URL=http://host.docker.internal:11434
OLLAMA_MODEL=qwen3.5:9b
```

На **Linux** `host.docker.internal` из коробки может не резолвиться. В `docker-compose.yml` у `web`/`worker` уже есть:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Альтернатива: `OLLAMA_URL=http://172.17.0.1:11434` (типичный docker0 на Linux).

Для OpenAI: `AI_PROVIDER=openai` в `.env` (опционально) и ключ в `/settings/ai/` в браузере.

Без AI воркер создаёт сделки с `created_without_ai=True` после retry.

---

## Telegram chat-bot (опционально)

1. Раскомментируй сервис `bot` в `docker-compose.yml`.
2. Войди как head → `/settings/bot/` → token и allowlist.
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

- Данные в volume `crm_data`. `docker compose down -v` **удаляет данные**.
- Для production с нагрузкой — PostgreSQL (потребует правки settings).
- web и worker делят один SQLite-файл: при бурсте возможны `database is locked`.
