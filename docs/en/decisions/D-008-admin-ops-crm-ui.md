# D-008: Admin Ops — CRM UI, not Telegram

**Date:** 2026-07-29  
**Status:** accepted

## Context

Originally the Telegram bot was assumed to be the main head interface for reviewing leads.

## Decision

Admin Ops = `/requests/` page in CRM UI for role `head`. The Telegram bot is an optional transport prototype, not the canonical Admin Ops UI.

New administrative features are added **in CRM UI**, not in the bot.

## Consequences

- `/requests/` is the primary head tool for lead moderation
- Telegram bot only implements read commands (`/recent`, `/errors`, `/stats`) and retry
- D-011: one `run_admin_bot` process uses two routers: admin + customer

## Links

- `.ai/docs/admin_ops.md`
- `.ai/docs/decisions.md#D-008`
