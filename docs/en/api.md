# API Reference

## Authentication

### Webhook

HMAC-SHA256 body signature:

```
X-Timestamp: <unix timestamp>
X-Signature: hex(hmac-sha256(WEBHOOK_SECRET, raw_body))
```

Replay window: ±5 minutes. Missing/invalid signature → 401.

```bash
body='{"external_id":"test-1","source":"site","name":"Ivan","phone":"+7 999 123-45-67","text":"Interested in Chery Tiggo"}'
ts=$(date +%s)
sig=$(printf '%s' "$body" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" -hex | sed 's/^.* //')
curl -i http://127.0.0.1:8000/api/v1/intake/lead \
  -H "Content-Type: application/json" \
  -H "X-Timestamp: $ts" \
  -H "X-Signature: $sig" \
  -d "$body"
```

### Admin API

Session (role=head) or header `X-Admin-Token: <ADMIN_API_TOKEN>`.

---

## Endpoints

### POST /api/v1/intake/lead

Create / deduplicate a lead.

**Optional header:** `X-Intake-Trust: internal` — after a valid HMAC signature, disables velocity signals (for server-to-server from one IP).

**Body:**
```json
{
  "external_id": "site-001",
  "name": "Ivan",
  "phone": "+7 999 123-45-67",
  "email": "ivan@example.test",
  "text": "Interested in Chery Tiggo on credit",
  "source": "site",
  "received_at": "2026-07-30T15:00:00+03:00",
  "metadata": {}
}
```

**Responses:**
- `202` — new request (`status: received`): `{"request_id": 1, "stored_request_id": 1}`
- `200` — duplicate `external_id`, a `duplicate` row was stored
- `401` — invalid signature

### GET /api/v1/deals/{id}

Deal by id. Managers see only their own; head sees all. `404` when access is denied.

### GET /api/v1/admin/requests/recent

Latest 10 requests (no raw payload). Access: head session or `X-Admin-Token`.

### GET /api/v1/admin/requests/errors

Requests in `retry_wait` and `failed`. Access: head session or `X-Admin-Token`.

### POST /api/v1/admin/requests/{id}/retry

Reprocess. Clears `locked_at`, `next_retry_at`, `last_error` → `received`. Writes `ProcessingLog.retried_manually`.

### OpenAPI UI

`/api/v1/docs` — Django Ninja interactive docs.

---

## Request statuses

| Status | Description |
|--------|-------------|
| `received` | Accepted, waiting for worker |
| `processing` | Locked by worker |
| `processed` | Processed, deal created |
| `suspicious` | Risk 60–89, waiting for head review |
| `blocked` | Risk 90+, blocklist, or explicit AI spam |
| `retry_wait` | AI error, will retry |
| `failed` | Attempts exhausted (5) |
| `duplicate` | Duplicate `external_id` |

---

## Risk scoring

| Score | Decision | Result |
|-------|----------|--------|
| 0–29 | process | Deal is created |
| 30–59 | risk_flagged | Deal with `risk_flagged=True` |
| 60–89 | suspicious | No deal |
| 90+ | blocked | No deal |

Final score = `max(rules_score, ai_score)`. AI cannot lower the rules score.
