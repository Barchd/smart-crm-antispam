# D-030: WebhookSettings — rotate HMAC secret via CRM UI

**Date:** 2026-07-30  
**Status:** accepted

## Context

`WEBHOOK_SECRET` lived only in `.env`. Rotating it required server access and a process restart.

## Decision

Model `intake.WebhookSettings` (singleton pk=1): `webhook_secret`, `updated_by`, `updated_at`.

Page `/settings/webhook/` (head-only):
1. Confirm modal
2. Generate via `secrets.token_urlsafe(32)`
3. New secret is shown **once** in the response body (not on GET)
4. GET shows only mask `***xxxx`

`signature_valid()` in `crm/api.py` reads the secret via `get_webhook_secret()`: DB → env fallback.

## Consequences

Rotation without editing `.env` or restarting. After change, the old secret stops working immediately.

## Links

- `.ai/docs/decisions.md#D-030`
