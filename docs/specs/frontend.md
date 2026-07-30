# Frontend Spec

## Стек

- Django Templates (server-rendered)
- Bootstrap 5.3 (CDN)
- Никакого отдельного JS-фреймворка — только нативный JS для UI-элементов (модалки Bootstrap, clipboard API)

## Шаблоны

```
templates/
  base.html              — navbar, flash-messages, Bootstrap
  registration/          — login, password change
  crm/
    deals_index.html     — список сделок с pipeline-badges
    deal_detail.html     — карточка сделки: pipeline-stepper, чат, AI-анализ, комментарии
    clients_index.html
    client_detail.html
    inbound_requests_index.html  — Admin Ops: карточки заявок
    includes/
      pipeline_step.html — один шаг воронки (цветной badge + кнопка)
  intake/
    lead_form.html       — mock-форма заявки (honeypot, CSRF)
    webhook_settings.html — ротация webhook-секрета
  bot/
    settings.html        — Telegram token, allowlist, customer prompt
  ai/
    settings.html        — AI подключения (список, редактор, check)
```

## UI-соглашения

- Все формы — POST с CSRF токеном
- Опасные действия (delete, spam, rotate key) — Bootstrap modal с confirm
- Ошибки выводятся через Django `messages` framework (flash-messages в base.html)
- Права проверяются на backend; в UI — декоративная скрытость через `{% if user.is_head %}`
- Токены и секреты в HTML не выводятся — только маска `***xxxx`

## Воронка (pipeline)

Файл: `crm/pipeline.py` — таблица допустимых переходов.

Stages: `new → first_contact → qualification → proposal → negotiation → won/lost`

- `won` — только из `negotiation`
- `lost` — из любого открытого этапа
- Закрытые (`won/lost`) — read-only
- Transition: POST `/deals/{id}/stage/` + backend-валидация

## Admin Ops (`/requests/`)

Карточка заявки содержит:
- Риск-панель: score/100, band (normal/risk_flagged/suspicious/blocked), причины
- AI-анализ: spam_probability, toxicity, troll, off_topic, summary
- Fingerprint-кластер: UA, IP, связанные заявки, уникальные контакты
- Лента сообщений (Dialog.messages + raw follow-up)
- ProcessingLog accordion
- Кнопки: retry, восстановить, спам, удалить (с confirm modal)
