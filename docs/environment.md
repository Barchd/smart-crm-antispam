# Переменные окружения

Минимальный `.env` для локальной разработки — только 4 переменные. Остальное опционально или вводится в UI.

---

## Обязательные

| Переменная | Описание | Пример |
|------------|----------|--------|
| `DJANGO_SECRET_KEY` | Django secret key | `python manage.py generate_tokens` |
| `DJANGO_DEBUG` | `true` для dev, `false` для prod | `true` |
| `DJANGO_ALLOWED_HOSTS` | Разрешённые хосты (через запятую) | `127.0.0.1,localhost` |
| `CRM_BASE_URL` | Базовый URL сервера | `http://127.0.0.1:8000` |

---

## Intake API

| Переменная | Описание | Примечание |
|------------|----------|-----------|
| `WEBHOOK_SECRET` | HMAC-ключ для подписи webhook | Можно также ротировать через `/settings/webhook/` |
| `ADMIN_API_TOKEN` | Токен для admin API endpoints | Для automation/CI |

Без `WEBHOOK_SECRET` в DEBUG-режиме webhook принимается без подписи. В production обязателен.

---

## AI (опциональные)

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `AI_PROVIDER` | `ollama` | `ollama` или `openai` |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | URL Ollama-сервера |
| `OLLAMA_MODEL` | `qwen3.5:9b` | Модель |
| `AI_BACKPRESSURE_ENABLED` | `true` | Защита от перегрузки |
| `AI_QUEUE_BACKPRESSURE_THRESHOLD` | `100` | Порог очереди |
| `AI_RETRY_BACKPRESSURE_THRESHOLD` | `10` | Порог retry-storm |
| `AI_RETRY_BACKPRESSURE_WINDOW_MINUTES` | `10` | Окно подсчёта retry |

> **OpenAI API key** — вводится в `/settings/ai/` в браузере (хранится в БД), **никогда не в `.env`**.

---

## Telegram (fallback, опционально)

| Переменная | Описание |
|------------|----------|
| `BOT_TOKEN` | Используется только если БД пуста; основной ввод — `/settings/bot/` |
| `ADMIN_CHAT_ID` | Числовой Telegram user id (fallback) |
| `ADMIN_TELEGRAM_IDS` | Allowlist через запятую или перенос строки (fallback) |

> После `migrate` — всё настраивается в `/settings/bot/`. `.env` нужен только для самого первого запуска.

---

## Seed-пароли (опциональные)

| Переменная | Описание |
|------------|----------|
| `CRM_HEAD_PASSWORD` | Пароль head при seed_users (если пусто — генерируется автоматически) |
| `CRM_MANAGER1_PASSWORD` | Пароль manager1 |
| `CRM_MANAGER2_PASSWORD` | Пароль manager2 |

---

## Rate limits (опциональные)

| Переменная | По умолчанию | Описание |
|------------|--------------|---------|
| `INTAKE_RATE_LIMIT_IP_PER_HOUR` | `20` | Заявок с одного IP в час |
| `INTAKE_RATE_LIMIT_GLOBAL_PER_MINUTE` | `60` | Глобальный лимит в минуту |
| `WORKER_LOCK_TIMEOUT_MINUTES` | `5` | Таймаут блокировки заявки воркером |
| `AI_MAX_ATTEMPTS` | `3` | Макс. попыток AI перед fallback |
| `PROCESSING_MAX_ATTEMPTS` | `5` | Макс. попыток воркера перед `failed` |

---

## Где хранятся секреты

| Секрет | Место хранения | Почему |
|--------|----------------|--------|
| `DJANGO_SECRET_KEY` | `.env` | Нужен до запуска БД |
| `WEBHOOK_SECRET` | `.env` или БД (`/settings/webhook/`) | Можно ротировать без перезапуска |
| OpenAI API key | БД (`/settings/ai/`) | Write-only в UI, не попадает в git |
| Telegram BOT_TOKEN | БД (`/settings/bot/`) | Write-only в UI, не попадает в git |
| `ADMIN_API_TOKEN` | `.env` | Для CI/automation |

**Правило:** никакие токены внешних сервисов (OpenAI, Telegram) не должны быть в `.env` или коде.
