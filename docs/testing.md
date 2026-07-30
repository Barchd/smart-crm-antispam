# Тестирование

## Запуск тестов

```bash
# Все тесты (270)
python manage.py test

# Конкретный модуль
python manage.py test intake.tests.test_risk
python manage.py test ai.tests.test_services
python manage.py test bot.tests

# Несколько модулей
python manage.py test intake ai.tests.test_services crm.tests channels.tests
```

## Структура тестов

| Файл | Что покрывает |
|------|--------------|
| `intake/tests/test_risk.py` | Rules risk scoring, blocklist, restore |
| `intake/tests/test_fingerprint_spam.py` | UA/IP flood, mass_identity, кластер |
| `intake/tests/test_trust_levels.py` | Trust levels (internal/external) |
| `intake/tests/test_webhook_settings.py` | WebhookSettings model и UI |
| `intake/tests/test_intake.py` | Webhook API, HMAC, rate limit, honeypot |
| `intake/tests/test_mass_spam.py` | Mass spam regression (25 заявок) |
| `ai/tests/test_services.py` | AI processing, spam detection, cluster context |
| `bot/tests/test_bot.py` | Bot services, retry guard, settings |
| `bot/tests/test_customer_flow.py` | Telegram FSM flow |
| `crm/tests/test_ui.py` | CRM UI: roles, deals, clients, Admin Ops |
| `crm/tests/test_permissions.py` | Backend permission checks |
| `crm/tests/test_domain.py` | Pipeline transitions |
| `channels/tests/` | Messaging adapters |

## Категории тестов

### Risk & антиспам

```bash
python manage.py test intake.tests.test_risk intake.tests.test_fingerprint_spam intake.tests.test_trust_levels
```

Покрывает: scoring thresholds, blocklist, ua_flood, ip_flood, fingerprint_mass_identity (≥4 contacts/24h → score 90 → blocked), trust_level exemptions.

### AI pipeline

```bash
python manage.py test ai.tests.test_services
```

Покрывает: explicit spam → blocked, phone_invalid → hide deal, backpressure, fingerprint_cluster in prompt.

### Admin Ops UI

```bash
python manage.py test crm.tests.test_ui
```

Покрывает: фильтры, поиск, retry, spam/restore, delete.

## Демо-заявки (осторожно)

Команды ниже создают реальные записи в БД — запускай только на dev/demo-инстансе:

```bash
# 12 демо-заявок через webhook
python manage.py send_demo_leads

# Fingerprint-спам demo (создаёт ~7 заявок с одного IP → все blocked)
python manage.py demo_spam_attack --scenario same-ua --count 7 --tag test1 \
  --process --rules-only
```

После demo_spam_attack — проверь `/requests/` под head: должны быть `blocked` с reason «много разных контактов с одного IP/User-Agent».

## CI-проверки

```bash
python manage.py check                         # Django system check
python manage.py test                          # все тесты
python manage.py makemigrations --check --dry-run  # нет незакоммиченных миграций
```

Секрет-скан (убедись что .env не попал в git):
```bash
grep -r 'SECRET_KEY\s*=' --include='*.py' .    # должно быть только из os.environ
```
