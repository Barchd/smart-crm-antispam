# API Spec

## Аутентификация

Два механизма:

### 1. HMAC webhook (intake)

```
X-Timestamp: <unix timestamp>
X-Signature: HMAC-SHA256(hex, WEBHOOK_SECRET, raw_body)
Replay window: ±5 min
```

Trust levels:
- `external` (default) — все velocity-проверки
- `internal` — `X-Intake-Trust: internal` + валидная подпись → skip velocity signals

### 2. Admin API

Session (role=head) **или** `X-Admin-Token: <ADMIN_API_TOKEN>`

---

## Схема роутинга

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

Тело (LeadIn schema):
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

Ответы: `202` (new), `200` (duplicate), `401` (bad HMAC)

### GET /api/v1/deals/{deal_id}

DealOut: `{id, title, stage, manager_id, client_id}`

Visibility: manager — только свои; head — все. `404` вместо `403`.

### GET /api/v1/admin/requests/recent
### GET /api/v1/admin/requests/errors
### POST /api/v1/admin/requests/{id}/retry

Доступ: session role=head OR `X-Admin-Token`.

---

## Schema validation

Django Ninja использует Pydantic. AI-ответ валидируется отдельной JSON-схемой с `strict=True` (OpenAI structured outputs) или `format` (Ollama).

Поля AI-ответа: `topic, need, urgency, category, spam_probability, toxicity, troll_probability, off_topic_probability, moderation_labels, department, suggested_employee_id, summary, suggested_reply`.

AI не может:
- Понизить risk score, установленный rules
- Изменить статус заявки напрямую
- Установить `blocked` без explicit spam вердикта (`category=spam`, label `spam` или `spam_probability >= 0.9`)
