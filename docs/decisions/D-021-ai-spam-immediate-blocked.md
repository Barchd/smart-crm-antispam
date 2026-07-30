# D-021: AI spam verdict → immediate blocked

**Дата:** 2026-07-30  
**Статус:** принято

## Контекст

AI-анализ возвращает `spam_probability`, но числовой порог (score 90+) мог не достигаться при низком rules score.

## Решение

Явный AI spam verdict игнорирует числовой порог:

- `analysis.category == "spam"` → `blocked`
- `"spam" in analysis.moderation_labels` → `blocked`
- `analysis.spam_probability >= 0.9` → `blocked`

Любое из трёх условий → немедленный `blocked` независимо от `risk_score_final`.

При `blocked`: `hide_deal_as_spam_for_request()` скрывает связанную сделку.

## Последствие

Модель может надёжно заблокировать очевидный spam с низким rules score (нет ссылок, нет брани, только «казино заработок» паттерн).

## Ссылки

- `.ai/docs/ai.md`
- `.ai/docs/decisions.md#D-021`
