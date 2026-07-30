# Security

## Secrets

### Storage rules

| Place | What to store |
|-------|---------------|
| `.env` (git-ignored) | `DJANGO_SECRET_KEY`, `ADMIN_API_TOKEN` (optional env fallback for webhook) |
| DB (UI `/settings/`) | OpenAI API key, Telegram BOT_TOKEN, webhook HMAC secret |
| Code / git | **Nothing** |

`.env` is in `.gitignore`. External service tokens must never live in source code.

### Webhook secret rotation

Primary storage is DB. Rotate without editing `.env` via CRM UI:
`/settings/webhook/` (head-only) → “Generate new” → shown once → copy to the integrator.

After rotation the old secret stops working immediately. Env `WEBHOOK_SECRET` is only a fallback.

### BOT_TOKEN leak

1. Revoke via BotFather in Telegram.
2. Log in as head → `/settings/bot/` → enter a new token.
3. Restart `python manage.py run_admin_bot`.
4. Check access logs.

---

## Roles and permissions

| Role | Access |
|------|--------|
| `manager` | Own clients and deals only; no `/requests/`, no settings |
| `head` | All data + Admin Ops + AI/bot/webhook settings |

Permissions are enforced on the backend (`is_head()`, `visible_to(user)`), not only in the UI.

---

## Webhook signature (HMAC)

All intake leads must be signed:

```
X-Timestamp: <unix timestamp>
X-Signature: HMAC-SHA256(WEBHOOK_SECRET, raw_body)
```

- Replay window: ±5 minutes.
- No signature → 401, no DB row.
- JSON body `trust` is ignored; `X-Intake-Trust: internal` works only after a valid signature.

---

## Antispam

- **rate_limit**: 20 leads/IP/hour, 60 global/min → `blocked`.
- **honeypot**: `website` form field → `blocked`.
- **blocklist**: phone/IP/email_domain → `blocked`.
- **fingerprint_mass_identity**: ≥4 distinct contacts from same IP/UA in 24h → score 90 → `blocked`.
- **trust_level=internal**: server-to-server with HMAC + `X-Intake-Trust: internal` → velocity signals skipped.

---

## Login throttling

- 5 failed attempts in 15 minutes → lock for 15 minutes.
- Attempts are stored in `crm.LoginAttempt`.

---

## AI prompt security

- Model output is validated against a JSON schema; untrusted data does not enter control flow.
- AI cannot lower the risk score set by rules.
- `customer_bot_prompt` (head setting) is added only to user JSON, not the system prompt.
- Telegram bot: head commands are protected by `AdminAccessMiddleware` + allowlist.

---

## PII masking

- The Telegram bot does not print name, phone, email, or lead text in chat.
- API error responses are sanitized (tokens never appear in messages).
- OpenAI API key is never returned in HTML (write-only form).
