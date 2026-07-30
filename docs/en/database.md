# Database

## Engine

SQLite (`db.sqlite3`). For production load you can switch to PostgreSQL — change `DATABASES` in `settings.py` and recreate/migrate.

## Models by app

### crm

| Model | Key fields |
|-------|------------|
| `User` | `role` (manager/head), `full_name`, `is_active` |
| `Client` | `phone_raw`, `phone_normalized` (E.164/RU), `manager`, `source` |
| `Deal` | `stage`, `client`, `manager`, `inbound_request`, `risk_flagged`, `is_spam`, `reply_draft` |
| `DealLog` | `action`, `old_value`, `new_value` |
| `DealComment` | `text`, `author` |

### intake

| Model | Purpose |
|-------|---------|
| `InboundRequest` | Raw lead, status, risk, AI fields, `trust_level` |
| `ProcessingLog` | Audit log of processing steps (`step`, `status`, `details_json`) |
| `Blocklist` | Blocks by phone/ip/email_domain |
| `IntakeThrottle` | Fixed-window rate limit counters |
| `IdempotencyKey` | source_type + external_id → first request |
| `WebhookSettings` | Singleton: webhook_secret + audit (updated_by/at) |

### channels

| Model | Purpose |
|-------|---------|
| `Channel` | Channel type (telegram, site, whatsapp…) |
| `Dialog` | Customer thread; Channel + Client + Deal |
| `Message` | Message (inbound/outbound), delivery status |
| `DeliveryLog` | Send log via adapter |

### ai / bot

| Model | Purpose |
|-------|---------|
| `AISettings` | AI connections (multiple, `is_default` flag) |
| `BotSettings` | Singleton: Telegram token + allowlist + customer_prompt |

## InboundRequest: main fields

```
id, external_id, source_type, source_name
phone_raw, phone_normalized, email_raw, name_raw, message_text
ip_address, user_agent, trust_level (external/internal)
raw_payload_json, payload_hash, headers_json
status, risk_score_rules, risk_score_final, spam_reason
ai_topic, ai_need, ai_category, ai_spam_probability, ai_summary
linked_client, linked_deal
risk_restored_at  -- manual restore moment (baseline score=59)
```

## Migrations

```bash
python manage.py migrate
python manage.py makemigrations           # after model changes
python manage.py makemigrations --check --dry-run   # verify
```

Migrations in git: `crm/migrations/`, `intake/migrations/`, `channels/migrations/`, `ai/migrations/`, `bot/migrations/`.
