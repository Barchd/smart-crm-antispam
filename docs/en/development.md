# Local development

## Requirements

- Python 3.14
- pip, venv
- `openssl` (for HMAC curl examples)
- Ollama (optional, for AI analysis)

## Install

```bash
git clone <repo-url>
cd <project>

python3.14 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env
```

Minimum `.env`:
```env
DJANGO_SECRET_KEY=   # see below
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
CRM_BASE_URL=http://127.0.0.1:8000
```

Generate local secrets:
```bash
python manage.py generate_tokens
# Copy DJANGO_SECRET_KEY, WEBHOOK_SECRET, ADMIN_API_TOKEN into .env
```

## Database and seed data

```bash
python manage.py migrate
python manage.py seed_users     # creates head + 2 managers; save passwords from output
python manage.py seed_demo      # optional: demo clients and deals
```

## Run (two terminals)

```bash
# Terminal 1: Django server
python manage.py runserver

# Terminal 2: inbound worker
python manage.py process_inbound
```

## URLs

| URL | Description |
|-----|-------------|
| http://127.0.0.1:8000/deals/ | CRM home |
| http://127.0.0.1:8000/requests/ | Admin Ops (head only) |
| http://127.0.0.1:8000/lead/ | Mock lead form |
| http://127.0.0.1:8000/api/v1/docs | OpenAPI |
| http://127.0.0.1:8000/settings/ai/ | AI provider (head) |
| http://127.0.0.1:8000/settings/bot/ | Telegram (head) |
| http://127.0.0.1:8000/settings/webhook/ | Webhook secret (head) |

## AI (Ollama)

```bash
# macOS
brew install ollama && ollama pull qwen3.5:9b && ollama serve

# Add to .env:
# AI_PROVIDER=ollama
# OLLAMA_URL=http://127.0.0.1:11434
# OLLAMA_MODEL=qwen3.5:9b
```

Without an AI provider, the worker creates deals with `created_without_ai=True` after 3 failed attempts.

## Telegram chat-bot (optional)

```bash
# Terminal 3
python manage.py run_admin_bot
```

Token and allowlist are set in CRM UI → `/settings/bot/` after login.

## Tests

```bash
python manage.py test
python manage.py makemigrations --check --dry-run
```

Details: [testing.md](testing.md)

## Demo leads

```bash
python manage.py send_demo_leads --process --fast-retry --max-steps 40
```
