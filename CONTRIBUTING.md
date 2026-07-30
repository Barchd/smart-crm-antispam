# Как участвовать в проекте

## Начало работы

- Fork → ветка → PR
- Локальная настройка: см. [docs/development.md](docs/development.md)

## Соглашения по коду

- Style guide: [docs/coding-style.md](docs/coding-style.md)
- Django conventions: fat services/models, thin views, без бизнес-логики в views
- Без хардкода секретов в коде
- Миграции обязательны при изменении моделей

## Тесты

- Обязательны для новых features и bugfix
- `python manage.py test` — все 270 тестов должны быть green
- Примеры: `intake/tests/test_fingerprint_spam.py`, `ai/tests/test_services.py`

## Архитектурный канон

- Решения: `.ai/docs/decisions.md` (для агентов) / `docs/decisions/` (для людей)
- Перед большими изменениями — создай ADR в `docs/decisions/`
- Файлы `.ai/` не редактировать без необходимости

## Безопасность

- Уязвимости: пишите в приватном канале, не в public issues
- Подробнее: [docs/security.md](docs/security.md)

## Pull Request

- Опиши изменения и тесты
- Убедись что `python manage.py test` зелёный
- `python manage.py makemigrations --check --dry-run` — без новых миграций
