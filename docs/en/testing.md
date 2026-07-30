# Testing

## Run tests

```bash
# All tests
python manage.py test

# Specific module
python manage.py test intake.tests.test_risk
python manage.py test ai.tests.test_services
python manage.py test bot.tests

# Several modules
python manage.py test intake ai.tests.test_services crm.tests channels.tests
```

## Test layout

| File | Coverage |
|------|----------|
| `intake/tests/test_risk.py` | Rules risk scoring, blocklist, restore |
| `intake/tests/test_fingerprint_spam.py` | UA/IP flood, mass_identity, cluster |
| `intake/tests/test_trust_levels.py` | Trust levels (internal/external) |
| `intake/tests/test_webhook_settings.py` | WebhookSettings model and UI |
| `intake/tests/test_intake.py` | Webhook API, HMAC, rate limit, honeypot |
| `intake/tests/test_mass_spam.py` | Mass spam regression (25 leads) |
| `ai/tests/test_services.py` | AI processing, spam detection, cluster context |
| `bot/tests/test_bot.py` | Bot services, retry guard, settings |
| `bot/tests/test_customer_flow.py` | Telegram FSM flow |
| `crm/tests/test_ui.py` | CRM UI: roles, deals, clients, Admin Ops |
| `crm/tests/test_permissions.py` | Backend permission checks |
| `crm/tests/test_domain.py` | Pipeline transitions |
| `channels/tests/` | Messaging adapters |

## Test categories

### Risk & antispam

```bash
python manage.py test intake.tests.test_risk intake.tests.test_fingerprint_spam intake.tests.test_trust_levels
```

Covers: scoring thresholds, blocklist, ua_flood, ip_flood, fingerprint_mass_identity (≥4 contacts/24h → score 90 → blocked), trust_level exemptions.

### AI pipeline

```bash
python manage.py test ai.tests.test_services
```

Covers: explicit spam → blocked, phone_invalid → hide deal, backpressure, fingerprint_cluster in prompt.

### Admin Ops UI

```bash
python manage.py test crm.tests.test_ui
```

Covers: filters, search, retry, spam/restore, delete.

## Demo leads (careful)

These commands create real DB rows — run only on a dev/demo instance:

```bash
# 12 demo leads via webhook
python manage.py send_demo_leads

# Fingerprint spam demo (~7 leads from one IP → all blocked)
python manage.py demo_spam_attack --scenario same-ua --count 7 --tag test1 \
  --process --rules-only
```

After `demo_spam_attack`, open `/requests/` as head: expect `blocked` with reason about many contacts from one IP/User-Agent.

## CI checks

```bash
python manage.py check                         # Django system check
python manage.py test                          # all tests
python manage.py makemigrations --check --dry-run  # no pending migrations
```

Secret scan (ensure `.env` is not in git):
```bash
grep -r 'SECRET_KEY\s*=' --include='*.py' .    # should only come from os.environ
```
