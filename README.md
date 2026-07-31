# Smart-crm-antispam для отдела продаж

Рабочий прототип CRM: роли manager/head, сделки, intake API, AI-анализ, Telegram-чат-бот.

## Docker (быстрый путь)

Без локального Python/venv — см. полную инструкцию: **[docs/deployment.md](docs/deployment.md)** · [EN](docs/en/deployment.md).

```bash
cp .env.example .env
# DJANGO_SECRET_KEY=$(openssl rand -hex 32)  — вставь в .env
# для доступа по IP: DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,ВАШ_IP

docker compose up --build -d
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_users   # сохрани пароли из вывода
# http://127.0.0.1:8000/
```

Ollama при обычном `up` **не** скачивается. AI/bot/webhook — через UI `/settings/*` (head).

## Быстрый старт (локальный Python)

Подробно: [INSTALL.md](INSTALL.md).

```bash
# 1. Создать и активировать виртуальное окружение
python3.14 -m venv .venv && source .venv/bin/activate

# 2. Установить зависимости
pip install -r requirements.txt

# 3. Настроить окружение
cp .env.example .env
# DJANGO_SECRET_KEY: openssl rand -hex 32  или  python manage.py generate_tokens

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

- [Установка с нуля](INSTALL.md)
- [Docker / деплой](docs/deployment.md) / [Deployment (EN)](docs/en/deployment.md)
- [Локальная разработка](docs/development.md) / [Development](docs/en/development.md)
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

## Для проверяющего (защита)

Обычные Python-скрипты (без Django): signed HTTP на живой `runserver`.

```bash
# Terminal A: python manage.py runserver
# Terminal B: process_inbound — на время атаки остановить (Ctrl+C)

python3 scripts/defense_spam_demo.py      # 10 заявок, РФ-номера, разные UA
python3 scripts/defense_spam_errors.py    # битые телефоны, toxic, 401, дубль

# потом снова: python manage.py process_inbound
```

Открой http://127.0.0.1:8000/requests/ (логин `head`) → IP `203.0.113.50` / `203.0.113.77`.

Подробнее: [INSTALL.md §12](INSTALL.md#12-демо-атака-для-защиты-проверяющему).

## Тесты

```bash
python manage.py test
```
