# Deployment

## Options

| Method | When to use |
|--------|-------------|
| [Local development](development.md) | Dev, debugging |
| Docker (this file) | Demo, staging, prod-like |

Full variable list: [environment.md](environment.md). Local Python path: [INSTALL.md](../../INSTALL.md) (Russian).

---

## Docker: quick start

### 1. Prepare `.env`

```bash
cp .env.example .env
```

Minimal set (same as `.env.example`):

```env
DJANGO_SECRET_KEY=          # see generation below
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
CRM_BASE_URL=http://127.0.0.1:8000
```

When `DJANGO_DEBUG=false`, also set:

```env
WEBHOOK_SECRET=
ADMIN_API_TOKEN=
```

**Secrets without local Python** (recommended for Docker):

```bash
# paste into .env
DJANGO_SECRET_KEY=$(openssl rand -hex 32)
WEBHOOK_SECRET=$(openssl rand -hex 32)
ADMIN_API_TOKEN=$(openssl rand -hex 32)
```

Or bring containers up first and generate inside the image:

```bash
docker compose up --build -d
docker compose exec web python manage.py generate_tokens
# copy output into host .env, then:
docker compose up -d --force-recreate
```

**Access beyond localhost** (server IP/domain, e.g. `194.135.33.204`):

```env
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,194.135.33.204
CRM_BASE_URL=http://194.135.33.204:8000
```

Otherwise Django returns `DisallowedHost`.

Prefer AI / Telegram / webhook secret via UI after start: `/settings/ai|bot|webhook/` (head). Do not put `OPENAI_API_KEY` or `BOT_TOKEN` in `.env` if you use the UI.

### 2. Build and run

```bash
docker compose up --build -d
```

### 3. Migrate and seed

```bash
docker compose exec web python manage.py migrate
```

Users and demo — **pick one**:

```bash
# option A — users only (passwords from THIS output):
docker compose exec web python manage.py seed_users

# option B — demo data (calls seed_users again inside;
# passwords from the first seed_users become invalid —
# use passwords from the seed_demo output):
docker compose exec web python manage.py seed_demo
```

To keep stable passwords across runs, set in `.env`:

```env
CRM_HEAD_PASSWORD=...
CRM_MANAGER1_PASSWORD=...
CRM_MANAGER2_PASSWORD=...
```

Final logins always come from the **last** `seed_users` / `seed_demo` output.

### 4. Open the browser

- Local: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- On a server: `http://YOUR_IP:8000/` (host must be in `DJANGO_ALLOWED_HOSTS`)

---

## Services

| Service | Command | Description |
|---------|---------|-------------|
| `web` | `runserver 0.0.0.0:8000` | Django server |
| `worker` | `process_inbound` | Worker: rules + AI |
| `bot` _(opt.)_ | `run_admin_bot` | Telegram customer chat-bot |
| `ollama` _(opt.)_ | image: ollama/ollama | Local AI (profile: ollama) |

Ollama is **not** pulled by a normal `docker compose up` — the service is commented out.

---

## AI

If Ollama runs on the **host** and CRM is in Docker:

```env
OLLAMA_URL=http://host.docker.internal:11434
OLLAMA_MODEL=qwen3.5:9b
```

On **Linux**, `host.docker.internal` may not resolve by default. `web` / `worker` already include:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Alternative: `OLLAMA_URL=http://172.17.0.1:11434` (typical docker0 on Linux).

For OpenAI: optional `AI_PROVIDER=openai` in `.env`, key in `/settings/ai/` in the browser.

Without AI, the worker creates deals with `created_without_ai=True` after retries.

---

## Telegram chat-bot (optional)

1. Uncomment `bot` in `docker-compose.yml`.
2. Log in as head → `/settings/bot/` → token and allowlist.
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

- Data lives in volume `crm_data`. `docker compose down -v` **deletes data**.
- For production load, use PostgreSQL (requires settings changes).
- web and worker share one SQLite file: `database is locked` is possible under bursts.
