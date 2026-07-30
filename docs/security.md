# Безопасность

## Секреты

### Правила хранения

| Место | Что хранить |
|-------|------------|
| `.env` (git-ignored) | `DJANGO_SECRET_KEY`, `WEBHOOK_SECRET`, `ADMIN_API_TOKEN` |
| БД (UI `/settings/`) | OpenAI API key, Telegram BOT_TOKEN |
| Код/git | **Ничего** |

`.env` в `.gitignore`. Никакие токены внешних сервисов не должны быть в коде.

### Ротация webhook-секрета

`WEBHOOK_SECRET` можно сменить без редактирования `.env` через CRM UI:
`/settings/webhook/` (head-only) → «Сгенерировать новый» → показывается один раз → скопировать на интегратора.

После смены старый секрет немедленно перестаёт работать.

### Утечка BOT_TOKEN

1. Отозвать через BotFather в Telegram.
2. Войти в CRM как head → `/settings/bot/` → ввести новый token.
3. `python manage.py run_admin_bot` (перезапуск).
4. Проверить логи доступа.

---

## Роли и права

| Роль | Доступ |
|------|--------|
| `manager` | Только свои клиенты и сделки; нет `/requests/`, нет settings |
| `head` | Все данные + Admin Ops + настройки AI/bot/webhook |

Права проверяются на backend (`is_head()`, `visible_to(user)`), не только в UI.

---

## Webhook-подпись (HMAC)

Все intake-заявки должны быть подписаны:

```
X-Timestamp: <unix timestamp>
X-Signature: HMAC-SHA256(WEBHOOK_SECRET, raw_body)
```

- Окно replay: ±5 минут.
- Без подписи → 401, строка в БД не создаётся.
- Значение `trust` из JSON-body игнорируется; `X-Intake-Trust: internal` работает только после валидной подписи.

---

## Антиспам

- **rate_limit**: 20 заявок/IP/час, 60 глобально/мин → заявка `blocked`.
- **honeypot**: поле `website` в форме → `blocked`.
- **blocklist**: phone/IP/email_domain → `blocked`.
- **fingerprint_mass_identity**: ≥4 разных контактов с одного IP/UA за 24ч → score 90 → `blocked`.
- **trust_level=internal**: server-to-server с HMAC + `X-Intake-Trust: internal` → velocity-сигналы не применяются.

---

## Login throttling

- 5 неверных попыток за 15 минут → блокировка на 15 минут.
- Попытки пишутся в `crm.LoginAttempt`.

---

## AI prompt security

- Ответ модели валидируется JSON-схемой; недоверенные данные не попадают в контрол-поток.
- AI не может понизить risk score, установленный правилами.
- `customer_bot_prompt` (настройка head) добавляется только в user JSON, не в system prompt.
- Telegram-бот: все команды head защищены `AdminAccessMiddleware` + allowlist.

---

## Маскирование PII

- Telegram-бот не выводит имя, телефон, email, текст заявки в чат.
- Ошибки в ответах API санитизируются (токены не попадают в error message).
- OpenAI API key не возвращается в HTML (write-only форма).
