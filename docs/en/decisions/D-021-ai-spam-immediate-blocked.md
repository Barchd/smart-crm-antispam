# D-021: AI spam verdict → immediate blocked

**Date:** 2026-07-30  
**Status:** accepted

## Context

AI analysis returns `spam_probability`, but the numeric threshold (score 90+) might not be reached when rules score is low.

## Decision

An explicit AI spam verdict ignores the numeric threshold:

- `analysis.category == "spam"` → `blocked`
- `"spam" in analysis.moderation_labels` → `blocked`
- `analysis.spam_probability >= 0.9` → `blocked`

Any of the three → immediate `blocked` regardless of `risk_score_final`.

On `blocked`: `hide_deal_as_spam_for_request()` hides the linked deal.

## Consequences

The model can reliably block obvious spam with a low rules score (no links, no profanity — only a “casino / earn money” pattern).

## Links

- `.ai/docs/ai.md`
- `.ai/docs/decisions.md#D-021`
