# API Spec

## Authentication

Two mechanisms:

### 1. HMAC webhook (intake)

```
X-Timestamp: <unix timestamp>
X-Signature: HMAC-SHA256(hex, WEBHOOK_SECRET, raw_body)
Replay window: ±5 min
```

Trust levels:
- `external` (default) — all velocity checks
- `internal` — `X-Intake-Trust: internal` + valid signature → skip velocity signals

### 2. Admin API

Session (role=head) **or** `X-Admin-Token: <ADMIN_API_TOKEN>`

---

## Routing map

```
config/urls.py:
  include crm/urls.py      → /deals/, /clients/, /requests/, /settings/...
  include intake/urls.py   → /lead/, /settings/webhook/
  include ai/urls.py       → /settings/ai/
  include bot/urls.py      → /settings/bot/
  api/v1/ → django-ninja   → /api/v1/intake/lead, /api/v1/deals/{id}, ...
```

## Endpoints (Django Ninja)

### POST /api/v1/intake/lead

Body (LeadIn schema):
```json
{
  "external_id": "string (required)",
  "name": "string",
  "phone": "string",
  "email": "string",
  "text": "string",
  "source": "string",
  "received_at": "ISO datetime (optional)",
  "metadata": {},
  "extra": {}
}
```

Responses: `202` (new), `200` (duplicate), `401` (bad HMAC)

### GET /api/v1/deals/{deal_id}

DealOut: `{id, title, stage, manager_id, client_id}`

Visibility: manager — own only; head — all. `404` instead of `403`.

### GET /api/v1/admin/requests/recent
### GET /api/v1/admin/requests/errors
### POST /api/v1/admin/requests/{id}/retry

Access: session role=head OR `X-Admin-Token`.

---

## Schema validation

Django Ninja uses Pydantic. AI responses are validated with a separate JSON schema (`strict=True` for OpenAI structured outputs, or `format` for Ollama).

AI response fields: `topic, need, urgency, category, spam_probability, toxicity, troll_probability, off_topic_probability, moderation_labels, department, suggested_employee_id, summary, suggested_reply`.

AI cannot:
- Lower the risk score set by rules
- Change request status directly
- Set `blocked` without an explicit spam verdict (`category=spam`, label `spam`, or `spam_probability >= 0.9`)
