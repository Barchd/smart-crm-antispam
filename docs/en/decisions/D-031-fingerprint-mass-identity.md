# D-031: fingerprint_mass_identity — long window → direct blocked

**Date:** 2026-07-30  
**Status:** accepted

## Context

Admin Ops showed a cluster of 6+ related leads with different contacts (IP 203.0.113.50), while risk was 1/100 — requests were not blocked because there was no long-window signal.

## Decision

Signal `fingerprint_mass_identity` (score=90, direct blocked):

| Window | Threshold | Effect |
|--------|-----------|--------|
| 24h | ≥4 distinct phone/email | score 90 → blocked |
| 7d | ≥6 distinct phone/email | score 90 → blocked |

Fingerprint: same IP **or** same UA (OR logic). Exempt: `trust_level=internal`, Telegram.

## Alternatives

- IP-only: rejected (one IP may be NAT for different people; UA pattern still matters)
- UA blocklist: rejected (too many false positives for popular UAs)

## Consequences

7 leads from one IP with different contacts → all `blocked`, no deal. Cluster is visible on the Admin Ops card.

## Links

- `.ai/docs/intake.md#fingerprint`
- `.ai/docs/decisions.md#D-031`
