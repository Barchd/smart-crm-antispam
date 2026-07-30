# Backend Spec

## Стек

- Python 3.14, Django 6.0
- Django Ninja (OpenAPI)
- SQLite (WAL mode)
- phonenumbers, pydantic, httpx, aiogram 3

## Структура приложений

```
crm/        — User, Client, Deal, DealLog, воронка, API deals
intake/     — InboundRequest, risk scoring, Admin Ops, WebhookSettings
ai/         — AISettings, prompt builder, OllamaClient/OpenAIClient
bot/        — BotSettings, aiogram FSM (customer + admin routers)
channels/   — Channel, Dialog, Message, DeliveryLog, adapters
config/     — settings.py, urls.py, wsgi.py
```

## Принципы

- Бизнес-логика в `**/services.py`, не во views
- Views: авторизация + вызов сервиса + render
- `@transaction.atomic` для всех операций записи
- Keyword-only args в сервисах: `def f(*, inbound: InboundRequest)`
- Миграции обязательны при изменении моделей

## Intake pipeline

1. POST `/api/v1/intake/lead` → `create_inbound_request()` → `InboundRequest(received)`
2. `process_inbound` worker → `acquire_next_request()` (atomic UPDATE)
3. `evaluate_rules(inbound)` → `RiskResult(score, signals, phone_valid)`
4. `process_request_with_ai(inbound, client)` → AI call → `max(rules, ai)`
5. `decision_for_score(score)` → process / risk_flagged / suspicious / blocked
6. `create_crm_entities_from_request(inbound)` → Client + Deal + Dialog

## Risk scoring

Файл: `intake/risk.py`

Пороги:
- `0–29` → process
- `30–59` → risk_flagged (Deal.risk_flagged=True)
- `60–89` → suspicious (сделка не создаётся)
- `90+` → blocked

Сигналы score=90 (direct blocked): `honeypot`, `rate_limit`, `fingerprint_mass_identity`

## Worker

Команда: `python manage.py process_inbound [--once] [--interval N]`

- Атомарный захват: `UPDATE status=processing WHERE status=received LIMIT 1`
- Stale lock recovery: заявки в `processing` старше `WORKER_LOCK_TIMEOUT_MINUTES` → `retry_wait`
- AI retry: до `AI_MAX_ATTEMPTS` попыток, затем fallback `created_without_ai=True`
- Worker retry: до `PROCESSING_MAX_ATTEMPTS`, затем `failed`

## Роли

```python
class RoleChoices(models.TextChoices):
    MANAGER = "manager"
    HEAD = "head"
```

Проверка: `is_head(request.user)`, `Deal.objects.visible_to(user)`.
