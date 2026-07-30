# P0 — Окружение и каркас

**Зависит от:** ничего
**Разделы SOLUTION.md:** 3, 4, 18

## Цель

Получить пустой, но запускающийся Django-проект с четырьмя приложениями, конфигурацией через `.env` и отсутствием секретов в коде. После этой фазы `manage.py check` проходит чисто, и можно писать модели.

## Предпосылки: риск окружения закрыт

Проверено до начала работы:

- в `.venv` стоит `Python 3.14.6`
- `Django 6.0` официально поддерживает `Python 3.12`, `3.13` и `3.14`

Значит менять интерпретатор не нужно, и задача `P0.1` из PLAN.md сводится к установке Django и фиксации версии.

Источник: [Django 6.0 release notes](https://docs.djangoproject.com/en/6.0/releases/6.0/).

## Решения этой фазы

### Переиспользуем существующий `.venv`, но `pip freeze` не применяем

В `.venv` уже стоят `Crawl4AI`, `aiohttp`, `beautifulsoup4` и ещё около сотни пакетов от краулера, которым собран `chatbot_context/`. Удалять окружение не нужно, оно не мешает.

Но `requirements.txt` пишется **руками**, а не через `pip freeze`. Иначе в поставку уедет сто пакетов краулера, и проверяющий будет полчаса ставить `torch`, чтобы посмотреть CRM.

Альтернатива, если хочется чистоты: создать отдельный `.venv-crm`. Не обязательно, но тогда `pip freeze` снова становится безопасным.

### Тесты на встроенном раннере Django, без `pytest`

`manage.py test` покрывает все 15 тестов из §25 SOLUTION.md. `pytest-django` дал бы более удобные фикстуры, но это лишняя зависимость и лишний конфиг в проекте.

### Четыре приложения, все в `INSTALLED_APPS`

`crm` и `intake` имеют модели. `ai` и `bot` моделей не имеют, но регистрируются как приложения тоже — так структура однородна, и каждое может держать свои тесты и management-команды. Приложение Django без моделей — это нормально и ничего не стоит.

### SQLite в режиме WAL

Это не косметика. К одной базе одновременно обращаются три процесса: веб, воркер и бот. В журнальном режиме по умолчанию писатель блокирует читателей, и воркер во время обработки заявки будет ронять веб-страницы с `database is locked`.

`WAL` снимает конфликт читателей с писателем, а `timeout` даёт процессам подождать вместо мгновенной ошибки.

## Ключевая ловушка фазы

**В этой фазе не выполняется `migrate`.**

В `P1` появится своя модель пользователя и `AUTH_USER_MODEL = "crm.User"`. Если сейчас применить миграции, Django создаст таблицу `auth_user`, и дальше подменить модель пользователя будет нельзя — придётся удалять `db.sqlite3` и начинать заново.

Порядок обязателен: сначала модель пользователя (`P1`), потом первый `migrate`.

По той же причине `AUTH_USER_MODEL` в `settings.py` в этой фазе **не прописывается** — иначе `manage.py check` упадёт на несуществующей модели, и критерий готовности не выполнится. Эта строка добавляется в `P1`.

## Целевое дерево файлов

```
crmtest/
├── manage.py
├── config/
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── crm/
│   ├── __init__.py
│   ├── apps.py
│   ├── models.py
│   ├── views.py
│   ├── admin.py
│   ├── migrations/__init__.py
│   └── tests/__init__.py
├── intake/          (та же структура)
├── ai/              (без models.py и migrations)
├── bot/             (без models.py и migrations)
├── templates/
│   └── base.html
├── static/
├── specs/
├── chatbot_context/     существующее, не трогаем
├── .env                 не в поставке
├── .env.example
├── .gitignore
├── requirements.txt
├── SOLUTION.md
└── PLAN.md
```

## Задачи

### P0.1 Установка зависимостей

```bash
.venv/bin/python -m pip install "Django>=6.0,<6.1" django-ninja python-dotenv phonenumbers aiogram httpx
```

Проверка:

```bash
.venv/bin/python -c "import django; print(django.get_version())"
```

Затем зафиксировать **фактически установленные** версии в `requirements.txt` через `==`. Точные патч-версии берутся из вывода `pip show`, а не выдумываются заранее.

Состав и назначение:

| Пакет | Зачем |
|---|---|
| `Django` | ядро |
| `django-ninja` | intake API и OpenAPI (§17) |
| `python-dotenv` | чтение `.env` |
| `phonenumbers` | нормализация телефона (§9.2) |
| `aiogram` | админский бот (§15) |
| `httpx` | вызов Ollama (§13) |

Если `django-ninja` окажется несовместим с Django 6.0 — это выясняется здесь, на первых минутах, а не в `P5`. План отхода: написать intake-эндпоинт обычным Django-view с ручной валидацией, а OpenAPI-документацию отдать статическим YAML. Требование §17 закрывается, теряется только автогенерация.

### P0.2 Каркас проекта

```bash
.venv/bin/python -m django startproject config .
.venv/bin/python manage.py startapp crm
.venv/bin/python manage.py startapp intake
.venv/bin/python manage.py startapp ai
.venv/bin/python manage.py startapp bot
mkdir -p templates static specs
```

В `ai/` и `bot/` удалить `models.py` и `migrations/` — моделей там не будет.

В каждом приложении создать пакет `tests/` вместо файла `tests.py`: тестов будет много, и в `P3` они начнут делиться по темам.

### P0.3 `settings.py`

Читатель `.env` в начале файла:

```python
from pathlib import Path
from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(name: str, default=None, *, required: bool = False) -> str | None:
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(f"Не задана обязательная переменная окружения {name}")
    return value


def env_bool(name: str, default: bool = False) -> bool:
    return str(os.environ.get(name, str(default))).strip().lower() in {"1", "true", "yes"}
```

Базовые параметры:

```python
SECRET_KEY = env("DJANGO_SECRET_KEY", required=True)
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]
```

`SECRET_KEY` без значения по умолчанию и с `required=True` — это и есть выполнение требования ТЗ про секреты: проект физически не поднимется с ключом из репозитория.

Приложения:

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "crm",
    "intake",
    "ai",
    "bot",
]
```

База данных:

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            "timeout": 20,
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
            "transaction_mode": "IMMEDIATE",
        },
    }
}
```

`transaction_mode: IMMEDIATE` берёт блокировку записи сразу при открытии транзакции. Это нужно для атомарного захвата заявки воркером из §7.3: иначе два процесса успевают прочитать одну строку до того, как первый её обновит.

Шаблоны и статика:

```python
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
```

Локаль:

```python
LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True
```

`USE_TZ = True` обязательно: `received_at`, `next_contact_at`, `locked_at` и окна троттлинга сравниваются между собой, и наивное время здесь даст тихие ошибки на час.

Вход:

```python
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/deals/"
LOGOUT_REDIRECT_URL = "/login/"
```

Ограничение размера запроса из §10.1:

```python
DATA_UPLOAD_MAX_MEMORY_SIZE = 64 * 1024
```

64 КБ с запасом хватает на заявку с телефоном, текстом и метаданными, и отсекает попытки залить в `raw_payload_json` мегабайт мусора.

Прикладные настройки отдельным блоком в конце:

```python
WEBHOOK_SECRET = env("WEBHOOK_SECRET", required=not DEBUG)
ADMIN_API_TOKEN = env("ADMIN_API_TOKEN", required=not DEBUG)

BOT_TOKEN = env("BOT_TOKEN")
ADMIN_CHAT_ID = env("ADMIN_CHAT_ID")
ADMIN_TELEGRAM_IDS = [
    int(x) for x in env("ADMIN_TELEGRAM_IDS", "").replace(" ", "").split(",") if x
]

OLLAMA_URL = env("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = env("OLLAMA_MODEL", "qwen3.5:9b")
CRM_BASE_URL = env("CRM_BASE_URL", "http://127.0.0.1:8000")

INTAKE_RATE_LIMIT_IP_PER_HOUR = 20
INTAKE_RATE_LIMIT_GLOBAL_PER_MINUTE = 60
LOGIN_MAX_ATTEMPTS = 5
LOGIN_ATTEMPT_WINDOW_MINUTES = 15
WORKER_LOCK_TIMEOUT_MINUTES = 5
AI_MAX_ATTEMPTS = 3
PROCESSING_MAX_ATTEMPTS = 5
```

Числа вынесены в настройки, а не зашиты в код: их придётся показывать на защите и, возможно, крутить на демо.

`WEBHOOK_SECRET` и `ADMIN_API_TOKEN` обязательны только когда `DEBUG` выключен. Так проверяющий поднимет проект без заполнения всех полей, а в боевом режиме пустой секрет не проедет.

`ADMIN_TELEGRAM_IDS` — расширение allowlist из §15.5. Эту переменную нужно добавить в список §18 SOLUTION.md при работе над `P9`.

### P0.4 `config/urls.py`

Пока только админка. Маршруты добавляются своими фазами: `/login/` в `P1`, `/clients/` и `/deals/` в `P4`, `/api/` и `/form/` в `P5`, `/inbound/` в `P6`.

```python
from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
]
```

### P0.5 `.env` и `.env.example`

`.env.example` — с пустыми значениями и комментариями, идёт в поставку:

```dotenv
# Django
DJANGO_SECRET_KEY=
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost

# Приём заявок: подпись внешнего webhook (§10.1)
WEBHOOK_SECRET=
# Доступ к admin API (§16.2)
ADMIN_API_TOKEN=

# Telegram-бот администратора (§15)
BOT_TOKEN=
ADMIN_CHAT_ID=
ADMIN_TELEGRAM_IDS=

# Локальная модель (§13). Только localhost, см. §14.6
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3.5:9b

# Для ссылок бота на сделки (§15.3)
CRM_BASE_URL=http://127.0.0.1:8000
```

`.env` создаётся копированием и заполняется реальными значениями. Ключ генерируется так:

```bash
.venv/bin/python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

### P0.6 `.gitignore`

```gitignore
.venv/
.venv-crm/
__pycache__/
*.py[cod]
.env
db.sqlite3
db.sqlite3-wal
db.sqlite3-shm
.DS_Store
```

Файлы `-wal` и `-shm` появляются именно из-за режима WAL — без этих строк они уедут в поставку.

Каталог не под git (`git init` не выполнялся). Файл создаётся сейчас, чтобы `.env` не попал в репозиторий, если git появится в `P11`.

### P0.7 `templates/base.html`

Минимальный каркас: `<html>`, блок `content`, навигация, вывод `messages`. Без CSS-фреймворка — по решению из PLAN.md интерфейс делается на голом HTML.

## Критерий готовности

```bash
.venv/bin/python -c "import django; print(django.get_version())"   # 6.0.x
.venv/bin/python manage.py check                                    # System check identified no issues
```

Дополнительно вручную:

- `manage.py check` проходит при заполненном `.env`
- при пустом `DJANGO_SECRET_KEY` проект падает с понятным сообщением, а не запускается с ключом по умолчанию
- `grep -rn "SECRET_KEY\s*=\s*[\"']" config/settings.py` не находит строкового литерала
- `migrate` **не выполнялся**, файла `db.sqlite3` нет

## Что в этой фазе не делается

- `migrate` и создание базы — `P1`
- `AUTH_USER_MODEL` — `P1`
- любые модели — `P1` и `P2`
- маршруты, кроме админки — по своим фазам
- `README.md` — `P11`

## Открытый вопрос на потом

`ai/` как имя приложения совпадает с распространённым именем пакета. Конфликтов с текущим набором зависимостей нет, но если в `P7` появится сторонний пакет с таким именем, приложение переименовывается в `enrich`. Проверить импорты в `P7`.
