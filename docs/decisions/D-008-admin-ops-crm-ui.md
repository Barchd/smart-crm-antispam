# D-008: Admin Ops — CRM UI, не Telegram

**Дата:** 2026-07-29  
**Статус:** принято

## Контекст

Изначально предполагалось, что Telegram-бот будет основным интерфейсом руководителя для разбора заявок.

## Решение

Admin Ops = страница `/requests/` в CRM UI для роли `head`. Telegram-бот — optional transport prototype, не канонический Admin Ops UI.

Новые Administrative функции добавляются **в CRM UI**, не в бот.

## Последствие

- `/requests/` — основной инструмент head для модерации заявок
- Telegram-бот реализует только команды чтения (`/recent`, `/errors`, `/stats`) и retry
- D-011: один process `run_admin_bot` использует два router-а: admin + customer

## Ссылки

- `.ai/docs/admin_ops.md`
- `.ai/docs/decisions.md#D-008`
