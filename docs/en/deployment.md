# Deployment

## Options

| Method | When to use |
|--------|-------------|
| [Local development](development.md) | Dev, debugging |
| Docker (this file) | Demo, staging, prod-like |

---

## Docker: quick start

### 1. Prepare `.env`

```bash
cp .env.example .env
```

Required values (see [environment.md](environment.md)):
```env
DJANGO_SECRET_KEY=   # python manage.py generate_tokens
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
CRM_BASE_URL=http://localhost:8000
WEBHOOK_SECRET=      # python manage.py generate_tokens
ADMIN_API_TOKEN=     # python manage.py generate_tokens
```

### 2. Build and run

```bash
docker compose up --build -d
```

### 3. Migrate and seed

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_users   # save passwords from output
# optional demo data:
docker compose exec web python manage.py seed_demo
```

### 4. Open the browser

[http://localhost:8000/](http://localhost:8000/)

---

## Services

| Service | Command | Description |
|---------|---------|-------------|
| `web` | `runserver 0.0.0.0:8000` | Django server |
| `worker` | `process_inbound` | Worker: rules + AI processing |
| `bot` _(opt.)_ | `run_admin_bot` | Telegram customer chat-bot |
| `ollama` _(opt.)_ | image: ollama/ollama | Local AI (profile: ollama) |

---

## AI

Default `AI_PROVIDER=ollama`. If Ollama runs **on the host**:
```env
OLLAMA_URL=http://host.docker.internal:11434
OLLAMA_MODEL=qwen3.5:9b
```

For OpenAI, set `AI_PROVIDER=openai` in `.env`; enter the key at `/settings/ai/` **in the browser** (not in `.env`).

Without an AI provider, the worker creates deals with `created_without_ai=True` (automatic fallback after 3 errors).

---

## Telegram chat-bot (optional)

1. Uncomment the `bot` service in `docker-compose.yml`.
2. Log in as head → `/settings/bot/` → enter Telegram Bot Token and allowlist.
3. `docker compose restart bot`

---

## Updates

```bash
docker compose down          # do NOT add -v (you will lose data)
git pull
docker compose up --build -d
docker compose exec web python manage.py migrate
```

---

## SQLite limitations

- Data lives in volume `crm_data`. `docker compose down -v` **deletes data** — use `down` without flags.
- For production load, replace SQLite with PostgreSQL (requires settings.py and migration changes).
- web and worker share one SQLite file: lock contention is possible under high load.
