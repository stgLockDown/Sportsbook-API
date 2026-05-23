# ADR-0003: PointsBet — leave scraper in place but flag US public API as deprecated

**Status:** Accepted
**Date:** 2026-Q2
**Decision-maker:** Repo owner
**Supersedes:** N/A
**Superseded by:** N/A

## Context

`scrapers/pointsbet.py` hits PointsBet's public US API at
`api.pointsbet.com/api/v2/competitions/{id}/events/featured` for odds.
The scraper was working fine prior to PointsBet's acquisition by Fanatics
Betting & Gaming (closed 2023). Post-acquisition, Fanatics has been
winding down the PointsBet US brand and the public API has lost most of
its data.

## Reconnaissance findings (2026-Q2)

Hitting `api.pointsbet.com/api/v2/competitions/{id}/events/featured`
directly (i.e. before the scraper's parsing layer):

| Sport      | competitionId | Response       | Events |
| ---------- | ------------- | -------------- | ------ |
| NBA        | 7176          | `{events:[2]}` | 2      |
| MLB        | 7592          | empty (54 B)   | 0      |
| NFL        | 7589          | empty (54 B)   | 0      |
| NHL        | 7596          | empty (54 B)   | 0      |
| NCAAF      | 7590          | empty (54 B)   | 0      |
| NCAAB      | 7178          | empty (54 B)   | 0      |
| EPL        | 7412          | empty (54 B)   | 0      |
| MMA        | 7602          | empty (54 B)   | 0      |
| Tennis ATP | 7413          | empty (54 B)   | 0      |
| Golf       | 7594          | empty (54 B)   | 0      |

The empty 54-byte responses are valid JSON (`{"events":[],"nextPage":null,…}`)
returned with HTTP 200 — i.e. the API itself is up but is returning no
events for any sport except NBA. This is **not a parser bug**. Hitting
the API with a fresh User-Agent, with cookies cleared, with a US IP via
proxy — every variant returns the same empty payloads.

The Australian tenant `pointsbet.com.au` exists but is fronted by
Cloudflare with bot-detection challenges, and routing requires a
residential AU IP we don't have provisioned today.

## Decision

Keep `scrapers/pointsbet.py` and the aggregator wiring **unchanged** —
NBA still works (2 events), and the day-to-day cost of leaving the
scraper enabled is one extra ~150 ms call per sport with no impact on
the rest of the response. We do not invest in:

* Polish / refactor of the scraper.
* AU tenant integration (Cloudflare + residential IP work).
* New competitionId mapping.

Going forward, treat PointsBet as **legacy / deprecated upstream**.
Coverage is "best-effort, NBA only" until either (a) Fanatics relaunches
PointsBet US with restored API coverage, or (b) we proactively kill the
scraper as part of a future scrapers cleanup pass.

## Consequences

**Pros:**
* Zero engineering investment for known-dead surface.
* If Fanatics ever turns the API back on, we already have a working
  scraper — no rewrite needed.
* The /sportsbooks list still advertises PointsBet honestly: it shows
  up in /sports response with whichever sports have ≥1 event.

**Cons:**
* Users querying `/odds/{sport}/pointsbet` for any sport other than NBA
  will get an empty response. This is the same behaviour as any
  off-season sport so should not surprise consumers.
* The book stays in our /sportsbooks list (advertised count is 69).
  If we eventually decide to drop PointsBet entirely (reduce list to
  68), it's a one-line removal from `aggregator.ALL_SPORTSBOOKS` plus
  the per-sport `SPORT_SLUGS` entries.

## Why this is different from BetMGM / Caesars

We solved BetMGM and Caesars by **routing through ActionNetwork** when
direct scraping was blocked (PerimeterX / AWS WAF Bot Control respectively;
see ADR-0001). PointsBet is different — ActionNetwork dropped PointsBet
from their feed when the brand wound down. There is no fallback aggregator
that has data for them, because there *is no data* in the upstream.

## References

* `scrapers/pointsbet.py` — scraper implementation (unchanged by this ADR).
* `scrapers/aggregator.py` — `SPORT_SLUGS[*][pointsbet]` mappings.
* PointsBet US shutdown reporting: SBC News, Legal Sports Report
  (Q3 2023 — Fanatics acquisition closed; Q1–Q2 2024 — PointsBet US
  brand transition). Cite as needed in any user-facing docs.
