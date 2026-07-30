# API Reference

## Аутентификация

### Webhook

HMAC-SHA256 подпись тела:

```
X-Timestamp: <unix timestamp>
X-Signature: hex(hmac-sha256(WEBHOOK_SECRET, raw_body))
```

Окно replay: ±5 минут. Без подписи → 401.

```bash
body='{"external_id":"test-1","source":"site","name":"Иван","phone":"+7 999 123-45-67","text":"Интересует Chery Tiggo"}'
ts=$(date +%s)
sig=$(printf '%s' "$body" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" -hex | sed 's/^.* //')
curl -i http://127.0.0.1:8000/api/v1/intake/lead \
  -H "Content-Type: application/json" \
  -H "X-Timestamp: $ts" \
  -H "X-Signature: $sig" \
  -d "$body"
```

### Admin API

Session (role=head) или заголовок `X-Admin-Token: <ADMIN_API_TOKEN>`.

---

## Endpoints

### POST /api/v1/intake/lead

Создать/дедублировать заявку.

**Опциональный заголовок:** `X-Intake-Trust: internal` — после валидной HMAC-подписи отключает velocity-сигналы (для server-to-server с одного IP).

**Тело:**
```json
{
  "external_id": "site-001",
  "name": "Иван",
  "phone": "+7 999 123-45-67",
  "email": "ivan@example.test",
  "text": "Интересует Chery Tiggo в кредит",
  "source": "site",
  "received_at": "2026-07-30T15:00:00+03:00",
  "metadata": {}
}
```

**Ответы:**
- `202` — новая заявка (`status: received`): `{"request_id": 1, "stored_request_id": 1}`
- `200` — дубль external_id, создана строка `duplicate`
- `401` — неверная подпись

### GET /api/v1/deals/{id}

Сделка по id. Менеджер видит только свои; head — все. `404` при отсутствии доступа.

### GET /api/v1/admin/requests/recent

Последние 10 заявок (без raw payload). Доступ: head session или `X-Admin-Token`.

### GET /api/v1/admin/requests/errors

Заявки в `retry_wait` и `failed`. Доступ: head session или `X-Admin-Token`.

### POST /api/v1/admin/requests/{id}/retry

Повторная обработка. Сбрасывает `locked_at`, `next_retry_at`, `last_error` → `received`. Пишет `ProcessingLog.retried_manually`.

### OpenAPI UI

`/api/v1/docs` — интерактивная документация Django Ninja.

---

## Статусы заявок

| Статус | Описание |
|--------|----------|
| `received` | Принята, ожидает воркера |
| `processing` | Захвачена воркером |
| `processed` | Обработана, создана сделка |
| `suspicious` | Risk 60–89, ждёт разбора head |
| `blocked` | Risk 90+, blocklist или явный AI-спам |
| `retry_wait` | AI-ошибка, будет повтор |
| `failed` | Исчерпаны попытки (5) |
| `duplicate` | Дубль external_id |

---

## Risk scoring

| Score | Решение | Результат |
|-------|---------|-----------|
| 0–29 | process | Сделка создаётся |
| 30–59 | risk_flagged | Сделка с `risk_flagged=True` |
| 60–89 | suspicious | Сделка не создаётся |
| 90+ | blocked | Сделка не создаётся |

Итоговый score = `max(rules_score, ai_score)`. AI не может понизить rules score.
