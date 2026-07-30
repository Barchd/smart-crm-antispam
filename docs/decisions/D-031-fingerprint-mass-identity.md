# D-031: fingerprint_mass_identity — длинное окно → direct blocked

**Дата:** 2026-07-30  
**Статус:** принято

## Контекст

Admin Ops показывал кластер из 6+ связанных заявок с разными контактами (IP 203.0.113.50), при этом risk = 1/100 — заявки не блокировались, потому что не было сигнала за длинное окно.

## Решение

Сигнал `fingerprint_mass_identity` (score=90, direct blocked):

| Окно | Порог | Эффект |
|------|-------|--------|
| 24ч | ≥4 distinct phone/email | score 90 → blocked |
| 7д | ≥6 distinct phone/email | score 90 → blocked |

Fingerprint: тот же IP **или** тот же UA (OR-логика). Exempt: `trust_level=internal`, Telegram.

## Альтернативы

- Только IP-based: отклонено (один IP = NAT может быть у разных людей, но UA паттерн важен)
- UA blocklist: отклонено (D-024 — слишком много false positives для popular UAs)

## Последствие

7 заявок с одного IP, разные контакты → все `blocked`, сделка не создаётся. Кластер виден в карточке Admin Ops.

## Ссылки

- `.ai/docs/intake.md#fingerprint`
- `.ai/docs/decisions.md#D-031`
