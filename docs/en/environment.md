# Environment variables

Minimal local `.env` needs only 4 variables. Everything else is optional or configured in the UI.

---

## Required

| Variable | Description | Example |
|----------|-------------|---------|
| `DJANGO_SECRET_KEY` | Django secret key | `python manage.py generate_tokens` |
| `DJANGO_DEBUG` | `true` for dev, `false` for prod | `true` |
| `DJANGO_ALLOWED_HOSTS` | Allowed hosts (comma-separated) | `127.0.0.1,localhost` |
| `CRM_BASE_URL` | Public server base URL | `http://127.0.0.1:8000` |

---

## Intake API

| Variable | Description | Note |
|----------|-------------|------|
| `WEBHOOK_SECRET` | HMAC key for webhook signing | Prefer rotation via `/settings/webhook/` (DB); env is fallback |
| `ADMIN_API_TOKEN` | Token for admin API endpoints | For automation/CI |

Without `WEBHOOK_SECRET` in DEBUG mode, webhooks may be accepted without a signature. Required in production when DB secret is empty.

---

## AI (optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_PROVIDER` | `ollama` | `ollama` or `openai` |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `qwen3.5:9b` | Model name |
| `AI_BACKPRESSURE_ENABLED` | `true` | Overload protection |
| `AI_QUEUE_BACKPRESSURE_THRESHOLD` | `100` | Queue threshold |
| `AI_RETRY_BACKPRESSURE_THRESHOLD` | `10` | Retry-storm threshold |
| `AI_RETRY_BACKPRESSURE_WINDOW_MINUTES` | `10` | Retry counting window |

> **OpenAI API key** is entered at `/settings/ai/` in the browser (stored in DB), **never in `.env`**.

---

## Telegram (fallback, optional)

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Used only if DB is empty; primary input is `/settings/bot/` |
| `ADMIN_CHAT_ID` | Numeric Telegram user id (fallback) |
| `ADMIN_TELEGRAM_IDS` | Allowlist, comma or newline separated (fallback) |

> After `migrate`, configure everything in `/settings/bot/`. `.env` is only for the very first bootstrap.

---

## Seed passwords (optional)

| Variable | Description |
|----------|-------------|
| `CRM_HEAD_PASSWORD` | Head password for `seed_users` (auto-generated if empty) |
| `CRM_MANAGER1_PASSWORD` | manager1 password |
| `CRM_MANAGER2_PASSWORD` | manager2 password |

---

## Rate limits (optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `INTAKE_RATE_LIMIT_IP_PER_HOUR` | `20` | Leads per IP per hour |
| `INTAKE_RATE_LIMIT_GLOBAL_PER_MINUTE` | `60` | Global per-minute limit |
| `WORKER_LOCK_TIMEOUT_MINUTES` | `5` | Worker lock timeout |
| `AI_MAX_ATTEMPTS` | `3` | Max AI attempts before fallback |
| `PROCESSING_MAX_ATTEMPTS` | `5` | Max worker attempts before `failed` |

---

## Where secrets live

| Secret | Storage | Why |
|--------|---------|-----|
| `DJANGO_SECRET_KEY` | `.env` | Needed before DB is available |
| Webhook HMAC secret | DB (`/settings/webhook/`), env fallback | Rotate without restart |
| OpenAI API key | DB (`/settings/ai/`) | Write-only UI, not in git |
| Telegram BOT_TOKEN | DB (`/settings/bot/`) | Write-only UI, not in git |
| `ADMIN_API_TOKEN` | `.env` | For CI/automation |

**Rule:** never put external service tokens (OpenAI, Telegram) in `.env` or source code.
