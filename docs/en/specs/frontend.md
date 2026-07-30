# Frontend Spec

## Stack

- Django Templates (server-rendered)
- Bootstrap 5.3 (CDN)
- No separate JS framework — native JS only for UI bits (Bootstrap modals, clipboard API)

## Templates

```
templates/
  base.html              — navbar, flash-messages, Bootstrap
  registration/          — login, password change
  crm/
    deals_index.html     — deals list with pipeline badges
    deal_detail.html     — deal card: pipeline stepper, chat, AI analysis, comments
    clients_index.html
    client_detail.html
    inbound_requests_index.html  — Admin Ops: request cards
    includes/
      pipeline_step.html — one pipeline step (colored badge + button)
  intake/
    lead_form.html       — mock lead form (honeypot, CSRF)
    webhook_settings.html — webhook secret rotation
  bot/
    settings.html        — Telegram token, allowlist, customer prompt
  ai/
    settings.html        — AI connections (list, editor, check)
```

## UI conventions

- All forms — POST with CSRF token
- Dangerous actions (delete, spam, rotate key) — Bootstrap confirm modal
- Errors via Django `messages` framework (flash messages in base.html)
- Permissions enforced on backend; UI only hides controls with `{% if user.is_head %}`
- Tokens/secrets are never rendered in HTML — only mask `***xxxx`

## Pipeline

File: `crm/pipeline.py` — allowed transitions table.

Stages: `new → first_contact → qualification → proposal → negotiation → won/lost`

- `won` — only from `negotiation`
- `lost` — from any open stage
- Closed (`won/lost`) — read-only
- Transition: POST `/deals/{id}/stage/` + backend validation

## Admin Ops (`/requests/`)

Request card contains:
- Risk panel: score/100, band (normal/risk_flagged/suspicious/blocked), reasons
- AI analysis: spam_probability, toxicity, troll, off_topic, summary
- Fingerprint cluster: UA, IP, related requests, unique contacts
- Message feed (Dialog.messages + raw follow-up)
- ProcessingLog accordion
- Buttons: retry, restore, spam, delete (with confirm modal)
