"""Django settings for the CRM MVP."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    """Read an environment variable with an optional hard requirement."""

    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(f"Не задана обязательная переменная окружения {name}")
    return value


def env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean env variable."""

    return str(os.environ.get(name, str(default))).strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    """Read an integer env variable."""

    return int(os.environ.get(name, str(default)))


_GENERATE_TOKENS_COMMAND = "generate_tokens" in sys.argv
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    "generate-tokens-command-placeholder" if _GENERATE_TOKENS_COMMAND else None,
    required=not _GENERATE_TOKENS_COMMAND,
)
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = [
    host.strip()
    for host in env("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]

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
    "channels",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            "timeout": 20,
            "transaction_mode": "IMMEDIATE",
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "crm.User"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/deals/"
LOGOUT_REDIRECT_URL = "/login/"

DATA_UPLOAD_MAX_MEMORY_SIZE = 64 * 1024

WEBHOOK_SECRET = env("WEBHOOK_SECRET", required=not DEBUG)
ADMIN_API_TOKEN = env("ADMIN_API_TOKEN", required=not DEBUG)
BOT_TOKEN = env("BOT_TOKEN")
ADMIN_CHAT_ID = env("ADMIN_CHAT_ID")
ADMIN_TELEGRAM_IDS = [
    int(item)
    for item in env("ADMIN_TELEGRAM_IDS", "").replace(" ", "").split(",")
    if item
]
AI_PROVIDER = env("AI_PROVIDER", "ollama").strip().lower()
AI_BACKPRESSURE_ENABLED = env_bool("AI_BACKPRESSURE_ENABLED", True)
AI_QUEUE_BACKPRESSURE_THRESHOLD = env_int("AI_QUEUE_BACKPRESSURE_THRESHOLD", 100)
AI_RETRY_BACKPRESSURE_THRESHOLD = env_int("AI_RETRY_BACKPRESSURE_THRESHOLD", 10)
AI_RETRY_BACKPRESSURE_WINDOW_MINUTES = env_int("AI_RETRY_BACKPRESSURE_WINDOW_MINUTES", 10)
AI_KB_ENABLED = env_bool("AI_KB_ENABLED", True)
AI_KB_MAX_CHUNKS = env_int("AI_KB_MAX_CHUNKS", 5)
AI_KB_MAX_CHARS = env_int("AI_KB_MAX_CHARS", 6000)
OLLAMA_URL = env("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = env("OLLAMA_MODEL", "qwen3.5:9b")
OPENAI_API_KEY = env("OPENAI_API_KEY")
OPENAI_BASE_URL = env("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = env("OPENAI_MODEL", "gpt-5.6-sol")
OPENAI_TRANSCRIPTION_MODEL = env("OPENAI_TRANSCRIPTION_MODEL", "gpt-transcribe")
CRM_BASE_URL = env("CRM_BASE_URL", "http://127.0.0.1:8000")

INTAKE_RATE_LIMIT_IP_PER_HOUR = 20
INTAKE_RATE_LIMIT_GLOBAL_PER_MINUTE = 60
LOGIN_MAX_ATTEMPTS = 5
LOGIN_ATTEMPT_WINDOW_MINUTES = 15
WORKER_LOCK_TIMEOUT_MINUTES = 5
AI_MAX_ATTEMPTS = 3
PROCESSING_MAX_ATTEMPTS = 5
