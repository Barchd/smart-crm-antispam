# D-029: Trust Levels для server-to-server intake

**Дата:** 2026-07-30  
**Статус:** принято

## Контекст

Внутренние системы (телефония, 1C, собственный backend) с одного IP блокировались velocity-сигналами (`ip_flood`, `ua_flood`) так же, как внешние спамеры.

## Решение

Поле `InboundRequest.trust_level`: `external` (default) | `internal`.

Устанавливается **сервером** после успешной HMAC-проверки по заголовку:
```
X-Intake-Trust: internal
```

Значение из JSON-body игнорируется. Telegram получает `trust_level=internal` автоматически.

Для `internal` пропускаются: `ip_flood`, `ip_multi_identity`, `ua_flood`, `ua_multi_identity`, `fingerprint_mass_identity`.

Текстовые сигналы и blocklist остаются активными для всех.

## Последствие

PHP-сайт и лендинги = `external`. Внутренние системы с HMAC = `internal`.

## Ссылки

- `.ai/docs/intake.md#trust-levels`
- `.ai/docs/decisions.md#D-029`
