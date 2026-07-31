# Troubleshooting

## Error: No module named 'django'

Virtualenv is not activated:
```bash
source .venv/bin/activate
```

## Error: DJANGO_SECRET_KEY is not set

```bash
cp .env.example .env
# without Python: openssl rand -hex 32
# or: python manage.py generate_tokens / docker compose exec web python manage.py generate_tokens
```

## DisallowedHost when opening by IP/domain

Add the host to `.env`:

```env
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,194.135.33.204
CRM_BASE_URL=http://194.135.33.204:8000
```

Recreate containers: `docker compose up -d --force-recreate`.

## Warning staticfiles.W004 (missing /app/static)

The repo includes `static/` (with `.gitkeep`). If an old volume lacks it, create the directory in the container or rebuild the volume. The warning is non-fatal.

## seed_demo passwords differ from earlier seed_users

`seed_demo` calls `seed_users` again and may rotate passwords. Use passwords from the **last** seed output, or set `CRM_*_PASSWORD` in `.env`.

## Worker does not create deals (requests stuck in retry_wait)

Usually the AI provider is unavailable. Options:

1. **Without AI**: deals are created after 3 attempts (fallback `created_without_ai=True`).
2. **Ollama not running**: `ollama serve`, or do not set `OLLAMA_URL`.
3. **Backpressure**: if `.env` has `AI_BACKPRESSURE_ENABLED=true` and the queue > 100 — lower the threshold or temporarily set `AI_BACKPRESSURE_ENABLED=false`.

Check statuses:
```bash
python manage.py send_demo_leads --process --fast-retry --max-steps 10
# or open /requests/ as head
```

## Telegram bot does not reply

1. Check token: CRM `/settings/bot/` → “Save and verify connection”.
2. Ensure `python manage.py run_admin_bot` is running.
3. Check allowlist: `ADMIN_CHAT_ID` or `ADMIN_TELEGRAM_IDS` must include your Telegram user id.

## Webhook signature rejected (401)

1. Does the secret in DB (`/settings/webhook/`) or `.env` match what the integrator uses?
2. Are server clocks in sync? Diff > 5 minutes → replay rejected.
3. If you rotated the secret in `/settings/webhook/`, did the integrator update?

Signature test:
```bash
body='{"external_id":"test","phone":"+79991234567","text":"test","source":"site"}'
ts=$(date +%s)
sig=$(printf '%s' "$body" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" -hex | sed 's/^.* //')
curl -i http://127.0.0.1:8000/api/v1/intake/lead \
  -H "Content-Type: application/json" \
  -H "X-Timestamp: $ts" \
  -H "X-Signature: $sig" \
  -d "$body"
```

## Leads blocked for no obvious reason (fingerprint_mass_identity)

Server-to-server traffic from one IP is caught by velocity rules.

Fix — send `X-Intake-Trust: internal` with a valid HMAC signature:
```bash
curl ... \
  -H "X-Intake-Trust: internal" \
  ...
```

Details: [api.md](api.md)

## Tests fail

```bash
python manage.py check            # Django system check
python manage.py makemigrations --check --dry-run  # pending migrations?
python manage.py test --verbosity=2  # verbose output
```

## Docker: data lost on restart

Do not use `docker compose down -v`. Use `docker compose down` only (no flags).
