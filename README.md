# Smart-crm-antispam для отдела продаж

Рабочий прототип CRM: роли manager/head, сделки, intake API, AI-анализ, Telegram-чат-бот.

## Быстрый старт

```bash
# 1. Создать и активировать виртуальное окружение
python3.14 -m venv .venv && source .venv/bin/activate

# 2. Установить зависимости
pip install -r requirements.txt

# 3. Настроить окружение
cp .env.example .env
# Отредактируй DJANGO_SECRET_KEY (или сгенерируй: python manage.py generate_tokens)

# 4. Применить миграции
python manage.py migrate

# 5. Создать пользователей (сохрани пароли из вывода)
python manage.py seed_users

# 6. Запустить (два терминала)
python manage.py runserver
python manage.py process_inbound   # терминал 2

# 7. Открыть браузер
# http://127.0.0.1:8000/  — логин head/manager из шага 5

# 8. (Опционально) AI, Telegram, webhook-секреты — через UI (не в .env)
# /settings/ai/  |  /settings/bot/  |  /settings/webhook/  (вход как head)
```

## Документация

Русский: [docs/](docs/) · English: [docs/en/](docs/en/)

- [Локальная разработка](docs/development.md) / [Development](docs/en/development.md)
- [Docker](docs/deployment.md) / [Deployment](docs/en/deployment.md)
- [API](docs/api.md) / [API (EN)](docs/en/api.md)
- [Окружение](docs/environment.md) / [Environment](docs/en/environment.md)
- [Архитектура](docs/architecture.md) / [Architecture](docs/en/architecture.md)
- [Безопасность](docs/security.md) / [Security](docs/en/security.md)
- [Тесты](docs/testing.md) / [Testing](docs/en/testing.md)
- [Troubleshooting](docs/troubleshooting.md) / [EN](docs/en/troubleshooting.md)

## Адреса (local)

- CRM: http://127.0.0.1:8000/deals/
- Admin Ops: http://127.0.0.1:8000/requests/ (только head)
- Настройки: http://127.0.0.1:8000/settings/ai/ | /settings/bot/ | /settings/webhook/
- Mock-форма: http://127.0.0.1:8000/lead/
- OpenAPI: http://127.0.0.1:8000/api/v1/docs

## Тесты

```bash
python manage.py test
```
