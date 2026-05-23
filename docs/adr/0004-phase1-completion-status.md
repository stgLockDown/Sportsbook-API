# ADR-0004 — Phase 1 Backlog Completion Status

**Date:** 2026-05-24
**Status:** Accepted
**Context:** End-of-phase status doc summarising what was fixed, what was deferred, and why. Companion to ADR-0002 (FanDuel soccer) and ADR-0003 (PointsBet deprecation).

## What was fixed

| Issue | PR | Outcome |
|-------|----|---------|
| FanDuel soccer 404 across all customPageIds | #10 | 0 → 146 events / 11 per-league slugs (`epl, mls, champions-league, europa-league, la-liga, serie-a, eredivisie, liga-mx, brazil-serie-a, world-cup, nwsl`) via `eventTypeId=1` + per-`competitionId` slicing |
| PointsBet upstream deprecated | #11 | Documented in ADR-0003; scraper retained for legacy-region fallback |
| bet365 cross-CL pollution (NBA/NCAAB/WNBA share CL=18; NFL/NCAAF share CL=12) | #12, #13 | Per-sport `SPORT_LEAGUE_FILTER` with word-boundary needle matching; contextual `SPORT_NEGATIVE_MARKERS` for orphan/generic-fallback fixtures. `/odds/nba/bet365` 24 events (12 generic + 5 WNBA + 5 virtual + 2 NBA) → 11 events (~all NBA-related) |

## What was deferred

| Issue | Reason | Re-visit trigger |
|-------|--------|------------------|
| **bet365 NFL** = 0 events | Scraper hits homepage pods + `ADDITIONAL_PODS_URL`. NFL is not promoted on basketball-heavy 2026-05 homepage. Architectural: would need NFL-specific pod URL recon | NFL season start (Sep 2026) — verify whether organic homepage pickup happens |
| **DK NFL** = 1 event (futures only) | Content, not bug. We are in May 2026 — NFL offseason. The single event returned is "NFL 2026/27 Season Winner" futures, scraped correctly | NFL season start (Sep 2026) — confirm game lines start flowing |
| **DK soccer** = 0 events | DK splits soccer by competition (same architecture as FD pre-#10). Current `SPORT_LEAGUE` maps `soccer → leagueId=40253` (EPL only). Mid-May 2026 = season wrap-up so empty results are partially content-driven, partially needing per-competition expansion | When new soccer season starts (Aug 2026) OR when bot needs DK soccer coverage. Mirror FD pattern: recon DK competitionIds, add per-league slugs |
| **BetMGM direct scraper** | Aggregator (`an_sportsbook` provider) already proxies BetMGM with adequate coverage. No rate-limit pain observed | If aggregator starts rate-limiting OR coverage gap appears |

## Production health snapshot (post-Phase 1)

| Sport / Book | Events | Notes |
|---|---|---|
| `/odds/nba/bet365` | 11 | NBA games + NBA-marked futures, no sibling pollution |
| `/odds/wnba/bet365` | 12 | All 5 explicit WNBA-tagged games + correct duplicates |
| `/odds/ncaab/bet365` | 5 | Generic-bucket only (no NCAAB games active mid-May) |
| `/odds/soccer/fanduel` | 146 | 11 league slugs; EPL slice has 11 events |
| `/odds/nfl/bet365` | 0 | Offseason / not on homepage; architectural |
| `/odds/nfl/draftkings` | 1 | Offseason futures only |
| `/odds/soccer/draftkings` | 0 | Per-competition routing not yet expanded |

## Decision

Phase 1 is closed. The backlog items above are tracked in this ADR and will be re-opened when their re-visit trigger fires. Phase 2 (ValorOdds Discord bot + ValorOdds website) starts now, building on top of the now-clean per-sport endpoints — particularly the FanDuel soccer expansion (146 events) and the per-league filtered bet365 outputs.
