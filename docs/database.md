# База данных

## Движок

SQLite (`db.sqlite3`). Для production с нагрузкой можно заменить на PostgreSQL — только `settings.py` DATABASES и пересоздание миграций.

## Модели по приложениям

### crm

| Модель | Ключевые поля |
|--------|--------------|
| `User` | `role` (manager/head), `full_name`, `is_active` |
| `Client` | `phone_raw`, `phone_normalized` (E.164/RU), `manager`, `source` |
| `Deal` | `stage`, `client`, `manager`, `inbound_request`, `risk_flagged`, `is_spam`, `reply_draft` |
| `DealLog` | `action`, `old_value`, `new_value` |
| `DealComment` | `text`, `author` |

### intake

| Модель | Назначение |
|--------|-----------|
| `InboundRequest` | Сырая заявка, статус, риск, AI-поля, `trust_level` |
| `ProcessingLog` | Аудит-лог шагов обработки (step, status, details_json) |
| `Blocklist` | Блокировка по phone/ip/email_domain |
| `IntakeThrottle` | Fixed-window rate limit counters |
| `IdempotencyKey` | source_type + external_id → первая заявка |
| `WebhookSettings` | Singleton: webhook_secret + audit (updated_by/at) |

### channels

| Модель | Назначение |
|--------|-----------|
| `Channel` | Тип канала (telegram, site, whatsapp…) |
| `Dialog` | Тред с клиентом; Channel + Client + Deal |
| `Message` | Сообщение (inbound/outbound), статус доставки |
| `DeliveryLog` | Лог отправки через adapter |

### ai / bot

| Модель | Назначение |
|--------|-----------|
| `AISettings` | Подключения AI (несколько, флаг `is_default`) |
| `BotSettings` | Singleton: Telegram token + allowlist + customer_prompt |

## InboundRequest: основные поля

```
id, external_id, source_type, source_name
phone_raw, phone_normalized, email_raw, name_raw, message_text
ip_address, user_agent, trust_level (external/internal)
raw_payload_json, payload_hash, headers_json
status, risk_score_rules, risk_score_final, spam_reason
ai_topic, ai_need, ai_category, ai_spam_probability, ai_summary
linked_client, linked_deal
risk_restored_at  -- момент ручного восстановления (baseline score=59)
```

## Миграции

```bash
python manage.py migrate
python manage.py makemigrations           # после изменения моделей
python manage.py makemigrations --check --dry-run   # проверить
```

Миграции в git: `crm/migrations/`, `intake/migrations/`, `channels/migrations/`, `ai/migrations/`, `bot/migrations/`.
