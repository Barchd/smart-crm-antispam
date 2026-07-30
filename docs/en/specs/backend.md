# Backend Spec

## Stack

- Python 3.14, Django 6.0
- Django Ninja (OpenAPI)
- SQLite (WAL mode)
- phonenumbers, pydantic, httpx, aiogram 3

## App layout

```
crm/        — User, Client, Deal, DealLog, pipeline, deals API
intake/     — InboundRequest, risk scoring, Admin Ops, WebhookSettings
ai/         — AISettings, prompt builder, OllamaClient/OpenAIClient
bot/        — BotSettings, aiogram FSM (customer + admin routers)
channels/   — Channel, Dialog, Message, DeliveryLog, adapters
config/     — settings.py, urls.py, wsgi.py
```

## Principles

- Business logic in `**/services.py`, not in views
- Views: auth + service call + render
- `@transaction.atomic` for all write operations
- Keyword-only args in services: `def f(*, inbound: InboundRequest)`
- Migrations are required when models change

## Intake pipeline

1. POST `/api/v1/intake/lead` → `create_inbound_request()` → `InboundRequest(received)`
2. `process_inbound` worker → `acquire_next_request()` (atomic UPDATE)
3. `evaluate_rules(inbound)` → `RiskResult(score, signals, phone_valid)`
4. `process_request_with_ai(inbound, client)` → AI call → `max(rules, ai)`
5. `decision_for_score(score)` → process / risk_flagged / suspicious / blocked
6. `create_crm_entities_from_request(inbound)` → Client + Deal + Dialog

## Risk scoring

File: `intake/risk.py`

Thresholds:
- `0–29` → process
- `30–59` → risk_flagged (Deal.risk_flagged=True)
- `60–89` → suspicious (no deal)
- `90+` → blocked

Signals with score=90 (direct blocked): `honeypot`, `rate_limit`, `fingerprint_mass_identity`

## Worker

Command: `python manage.py process_inbound [--once] [--interval N]`

- Atomic acquire: `UPDATE status=processing WHERE status=received LIMIT 1`
- Stale lock recovery: `processing` older than `WORKER_LOCK_TIMEOUT_MINUTES` → `retry_wait`
- AI retry: up to `AI_MAX_ATTEMPTS`, then fallback `created_without_ai=True`
- Worker retry: up to `PROCESSING_MAX_ATTEMPTS`, then `failed`

## Roles

```python
class RoleChoices(models.TextChoices):
    MANAGER = "manager"
    HEAD = "head"
```

Checks: `is_head(request.user)`, `Deal.objects.visible_to(user)`.
