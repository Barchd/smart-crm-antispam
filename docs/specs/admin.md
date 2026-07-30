# Admin & Roles Spec

## Роли

| Роль | Описание |
|------|----------|
| `manager` | Видит и редактирует только свои Client/Deal/Dialog |
| `head` | Видит всё + Admin Ops + все settings |

Проверяется на backend в каждом view и API endpoint. Менеджер не может обойти через прямой URL или API.

## Admin Ops (`/requests/`)

Страница доступна **только** роли `head`. Backend: `if not is_head(request.user): raise PermissionDenied`.

### Возможности

- Фильтры: Все / Suspicious / Errors / Processed / Blocked
- Поиск по phone, id, AI-теме, потребности
- Карточка заявки: риск, AI, сообщения, ProcessingLog, fingerprint-кластер
- Действия: retry (only for retry_wait/failed), восстановить (suspicious/blocked), спам, удалить

### Действие «восстановить»

1. Удаляет совпадающие phone/IP/email из Blocklist
2. Устанавливает `risk_restored_at` (baseline score = 59)
3. Принудительно перезапускает обработку заявки
4. Скрытая сделка возвращается в CRM

### Действие «спам»

1. Добавляет phone/IP/email в Blocklist
2. Устанавливает `Deal.is_spam=True` (сделка скрыта, не удалена)
3. Статус → `blocked`

### Удаление заявки

- Удаляет `InboundRequest` + `ProcessingLog`
- `Client` и `Deal` **не удаляются**
- Очищает `Deal.inbound_request_id` перед удалением

## Settings (только `head`)

| URL | Что настраивается |
|-----|-------------------|
| `/settings/ai/` | AI-провайдеры (Ollama/OpenAI), несколько подключений, default |
| `/settings/bot/` | Telegram token (write-only), allowlist, customer prompt |
| `/settings/webhook/` | HMAC-секрет (генерация + одноразовый показ) |

Все токены/ключи write-only в форме: вводятся, сохраняются в БД, в HTML возвращается только маска.

## Безопасность Admin

- Login throttling: 5 попыток за 15 мин → блокировка
- Password change: каждый пользователь может сменить свой пароль
- Создание/удаление пользователей: только `head`
- Самоудаление запрещено; при наличии CRM-данных — `is_active=False` вместо DELETE

## Telegram bot admin access

Команды бота (`/recent`, `/errors`, `/retry`, `/stats`) защищены:
- `AdminAccessMiddleware`: только приватные чаты
- Allowlist из `BotSettings.admin_chat_id` + `admin_telegram_ids`
- `CommandRateLimiter`: 5 команд/минуту/пользователь
