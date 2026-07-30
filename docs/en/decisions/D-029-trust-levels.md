# D-029: Trust Levels for server-to-server intake

**Date:** 2026-07-30  
**Status:** accepted

## Context

Internal systems (telephony, 1C, own backend) from one IP were blocked by velocity signals (`ip_flood`, `ua_flood`) the same way as external spammers.

## Decision

Field `InboundRequest.trust_level`: `external` (default) | `internal`.

Set by the **server** after a successful HMAC check from header:
```
X-Intake-Trust: internal
```

JSON body value is ignored. Telegram gets `trust_level=internal` automatically.

For `internal`, these are skipped: `ip_flood`, `ip_multi_identity`, `ua_flood`, `ua_multi_identity`, `fingerprint_mass_identity`.

Text signals and blocklist stay active for everyone.

## Consequences

PHP sites and landings = `external`. Internal systems with HMAC = `internal`.

## Links

- `.ai/docs/intake.md#trust-levels`
- `.ai/docs/decisions.md#D-029`
