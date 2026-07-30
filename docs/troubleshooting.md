# Troubleshooting

## Ошибка: No module named 'django'

Виртуальное окружение не активировано:
```bash
source .venv/bin/activate
```

## Ошибка: DJANGO_SECRET_KEY не задан

```bash
cp .env.example .env
python manage.py generate_tokens   # скопируй DJANGO_SECRET_KEY в .env
```

## Воркер не создаёт сделки (заявки в retry_wait)

Обычно — AI-провайдер недоступен. Варианты:

1. **Без AI**: заявки создадут сделки после 3 попыток (fallback `created_without_ai=True`).
2. **Ollama не запущен**: `ollama serve` или отключи AI: не задавай `OLLAMA_URL`.
3. **Backpressure**: если в `.env` `AI_BACKPRESSURE_ENABLED=true` и очередь > 100 — снизи порог или временно поставь `AI_BACKPRESSURE_ENABLED=false`.

Проверить статусы:
```bash
python manage.py send_demo_leads --process --fast-retry --max-steps 10
# или зайди в /requests/ под head
```

## Telegram-бот не отвечает

1. Проверь token: CRM `/settings/bot/` → «Сохранить и проверить подключение».
2. Убедись что `python manage.py run_admin_bot` запущен.
3. Проверь allowlist: `ADMIN_CHAT_ID` или `ADMIN_TELEGRAM_IDS` должны содержать твой Telegram user id.

## Подпись webhook отклоняется (401)

1. `WEBHOOK_SECRET` в `.env` совпадает с тем, что использует интегратор?
2. Часы сервера синхронизированы? Разница > 5 минут → replay rejected.
3. Новый секрет через `/settings/webhook/` — обновил ли интегратор?

Тест подписи:
```bash
body='{"external_id":"test","phone":"+79991234567","text":"test","source":"site"}'
ts=$(date +%s)
sig=$(printf '%s' "$body" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" -hex | sed 's/^.* //')
curl -i http://127.0.0.1:8000/api/v1/intake/lead \
  -H "Content-Type: application/json" \
  -H "X-Timestamp: $ts" \
  -H "X-Signature: $sig" \
  -d "$body"
```

## Заявки блокируются без причины (fingerprint_mass_identity)

Сервер-to-сервер с одного IP блокируется velocity-правилами.

Решение — передавай `X-Intake-Trust: internal` с HMAC-подписью:
```bash
curl ... \
  -H "X-Intake-Trust: internal" \
  ...
```

Подробнее: [docs/api.md](api.md)

## Тесты падают

```bash
python manage.py check            # Django system check
python manage.py makemigrations --check --dry-run  # нет незакоммиченных миграций?
python manage.py test --verbosity=2  # подробный вывод
```

## Docker: данные теряются при restart

Не используй `docker compose down -v`. Только `docker compose down` (без флагов).
