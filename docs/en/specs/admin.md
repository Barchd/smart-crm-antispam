# Admin & Roles Spec

## Roles

| Role | Description |
|------|-------------|
| `manager` | Sees and edits only own Client/Deal/Dialog |
| `head` | Sees everything + Admin Ops + all settings |

Enforced on the backend in every view and API endpoint. Managers cannot bypass via direct URL or API.

## Admin Ops (`/requests/`)

Page is available **only** to role `head`. Backend: `if not is_head(request.user): raise PermissionDenied`.

### Capabilities

- Filters: All / Suspicious / Errors / Processed / Blocked
- Search by phone, id, AI topic, need
- Request card: risk, AI, messages, ProcessingLog, fingerprint cluster
- Actions: retry (only for retry_wait/failed), restore (suspicious/blocked), spam, delete

### “Restore” action

1. Removes matching phone/IP/email from Blocklist
2. Sets `risk_restored_at` (baseline score = 59)
3. Force-reprocesses the request
4. Hidden deal returns to CRM

### “Spam” action

1. Adds phone/IP/email to Blocklist
2. Sets `Deal.is_spam=True` (deal hidden, not deleted)
3. Status → `blocked`

### Delete request

- Deletes `InboundRequest` + `ProcessingLog`
- `Client` and `Deal` are **not** deleted
- Clears `Deal.inbound_request_id` before delete

## Settings (`head` only)

| URL | What is configured |
|-----|--------------------|
| `/settings/ai/` | AI providers (Ollama/OpenAI), multiple connections, default |
| `/settings/bot/` | Telegram token (write-only), allowlist, customer prompt |
| `/settings/webhook/` | HMAC secret (generate + one-time reveal) |

All tokens/keys are write-only in forms: entered, stored in DB, HTML returns only a mask.

## Admin security

- Login throttling: 5 attempts in 15 min → lockout
- Password change: every user can change their own password
- Create/delete users: `head` only
- Self-delete forbidden; if CRM data exists — `is_active=False` instead of DELETE

## Telegram bot admin access

Bot commands (`/recent`, `/errors`, `/retry`, `/stats`) are protected by:
- `AdminAccessMiddleware`: private chats only
- Allowlist from `BotSettings.admin_chat_id` + `admin_telegram_ids`
- `CommandRateLimiter`: 5 commands/minute/user
