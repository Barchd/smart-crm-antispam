# D-030: WebhookSettings — ротация HMAC-секрета через CRM UI

**Дата:** 2026-07-30  
**Статус:** принято

## Контекст

`WEBHOOK_SECRET` жил только в `.env`. Перевыпуск секрета требовал доступа к серверу и перезапуска процесса.

## Решение

Модель `intake.WebhookSettings` (singleton pk=1): `webhook_secret`, `updated_by`, `updated_at`.

Страница `/settings/webhook/` (head-only):
1. Confirm modal
2. Генерация через `secrets.token_urlsafe(32)`
3. Новый секрет показывается **один раз** в response body (не при GET)
4. GET показывает только маску `***xxxx`

`signature_valid()` в `crm/api.py` читает секрет через `get_webhook_secret()`: DB → env fallback.

## Последствие

Ротация без правки `.env` и перезапуска. После смены старый секрет немедленно перестаёт работать.

## Ссылки

- `.ai/docs/decisions.md#D-030`
