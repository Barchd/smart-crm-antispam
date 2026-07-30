# Changelog

All notable changes to this project will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

## [Unreleased]

### Added

- CRM: роли manager/head, клиенты, сделки, воронка (new→won/lost), журнал действий DealLog
- CRM: строгий порядок переходов воронки (backend validation в crm/pipeline.py)
- Intake: HMAC-подписанный webhook API (POST /api/v1/intake/lead), rate limit, honeypot, дедупликация
- Intake: rules-based risk scoring (30+ сигналов, score 0–100, blocklist)
- AI: Ollama/OpenAI provider (AISettings в БД), spam/toxicity classification, suggested reply
- AI: backpressure protection при перегрузке очереди
- Admin Ops: /requests/ — карточки заявок, retry, восстановление из спама, fingerprint-кластер
- Messaging: channel adapters (site mock, Telegram), Dialog/Message/DeliveryLog
- Telegram: customer intake (FSM: имя→телефон→вопрос→InboundRequest, follow-up)
- Security: fingerprint_mass_identity (≥4 контакта/24ч или ≥6/7д → score 90 → blocked)
- Security: trust_level=internal для server-to-server вызовов (X-Intake-Trust: internal + HMAC)
- WebhookSettings: ротация HMAC-секрета через CRM UI /settings/webhook/ (head-only)
- BotSettings: Telegram token и allowlist через /settings/bot/ (не в .env)
- AISettings: несколько подключений, default flag, проверка через getMe/ping
- Unicode case-insensitive search на SQLite (кириллица)
- Demo commands: send_demo_leads, demo_spam_attack (fingerprint flood demo)
