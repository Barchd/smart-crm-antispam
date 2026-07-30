# D-009: Customer Messaging separated from Admin Ops

**Date:** 2026-07-29  
**Status:** accepted

## Context

Telegram can be both a customer channel and an admin tool. Mixing these contours creates architectural risk.

## Decision

Two independent contours:

| Contour | Purpose | UI |
|---------|---------|-----|
| Admin Ops | Lead moderation, retry, stats | `/requests/` (head) |
| Customer Messaging | Manager ↔ customer chat | `/deals/{id}/` (chat block) |

Channel adapters (`channels/`) are a plugin layer. Replacing Telegram with WhatsApp needs a new adapter only, not a domain rewrite.

## Consequences

- `channels.Dialog` is bound to client and deal, not to the inbound request
- Managers see only their own dialogs
- Outbound messages always require manager confirmation (no auto-send)

## Links

- `.ai/docs/messaging.md`
- `.ai/docs/decisions.md#D-009`
