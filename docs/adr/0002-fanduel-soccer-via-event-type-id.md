# ADR-0002: FanDuel soccer served via `eventTypeId`, not `customPageId`

**Status:** Accepted
**Date:** 2026-Q2
**Decision-maker:** Repo owner
**Supersedes:** N/A
**Superseded by:** N/A

## Context

The FanDuel scraper (`scrapers/fanduel.py`) hits FD's state-tenant SB API at
`sbapi.{state}.sportsbook.fanduel.com/api/content-managed-page` for odds.

For US team sports the routing is:

```
GET /api/content-managed-page?page=CUSTOM&customPageId={slug}&_ak={key}
```

where `slug` is `nfl`, `nba`, `mlb`, `nhl`, `ncaaf`, `ncaab`, `wnba`, `ufc`,
`tennis`, `golf`, `boxing`. These all return a payload with the
`attachments.events` / `attachments.markets` shape we parse.

Soccer needs a different routing strategy.

## Reconnaissance findings (soccer)

We confirmed in 2026-Q2 that **none** of the obvious soccer customPageId
slugs work:

| `customPageId`               | HTTP   |
| ---------------------------- | ------ |
| `epl`                        | 404    |
| `mls`                        | 404    |
| `champions-league`           | 404    |
| `soccer`                     | 404    |
| `soccer-football`            | 404    |
| `england-premier-league`     | 404    |
| `europe-champions-league`    | 404    |
| `usa-mls`                    | 404    |

All return the same 14-byte `{"error": true}` body.

However, FD also accepts a **Betfair-style super-sport routing**:

```
GET /api/content-managed-page?page=SPORT&eventTypeId={int}&_ak={key}
```

`eventTypeId=1` returns Soccer (the legacy Betfair `eventTypeId` for
soccer; FD inherits Betfair's identifier scheme via Flutter Entertainment).
This single call returns ~140+ events across ~85 competitions including:

| Competition                  | `competitionId` |
| ---------------------------- | --------------- |
| English Premier League       | 10932509        |
| US MLS                       | 141             |
| UEFA Champions League        | 228             |
| Spanish La Liga              | 117             |
| Italian Serie A              | 81              |
| Dutch Eredivisie             | 9404054         |
| Liga MX                      | 5627174         |
| Brazilian Serie A            | 13              |
| FIFA World Cup               | 12469077        |
| US NWSL                      | 12331715        |
| UEFA Europa Conference Lg    | 12375833        |

Other major leagues (German Bundesliga, French Ligue 1, etc.) appear
in the payload only while their season is active. Adding them is
trivial once they show up — see `_session_todo.md` recon notes for the
discovery query.

The payload shape for `page=SPORT` is identical to `page=CUSTOM`:
`attachments.events` and `attachments.markets`. The only schema
addition is that each event carries `competitionId`, which we use to
filter the payload down to a per-league snapshot.

## Decision

`scrapers/fanduel.py:SPORT_MAP` carries two routing keys per sport:

* `customPageId` (default) — when the entry has no `event_type_id`.
* `event_type_id` — when set, the request switches to `page=SPORT`.
  An optional `competition_id` then filters the parsed events down to
  a single league.

Soccer entries (`soccer`, `epl`, `mls`, `champions-league`, `la-liga`,
`serie-a`, `eredivisie`, `liga-mx`, `brazil-serie-a`, `world-cup`,
`nwsl`, `europa-league`) all use `event_type_id=1`. The bare `soccer`
slug returns the full multi-league payload; per-league slugs filter to
a single `competition_id`.

The aggregator's `soccer` sport routes to FanDuel slug `soccer` (full
payload) so `/odds/soccer/fanduel` returns every soccer event FD
exposes today.

## Consequences

**Pros:**
* Single upstream call serves every soccer league — no N+1 fetch.
* Per-league slugs (e.g. `epl`, `mls`) are zero-cost slices of the
  same cached payload.
* Discovery is mechanical: any new soccer competition that shows up
  in FD's payload can be added by extracting its `competitionId` from
  `attachments.competitions` and adding a `SPORT_MAP` entry.
* No new dependencies, no new auth, no new bot-protection surface.

**Cons:**
* `eventTypeId` is a stable but undocumented Betfair-derived
  identifier. If FD switches to a fresh ID scheme, every soccer slug
  breaks at once. Mitigation: `scripts/recon/fd_soccer_recon.py`
  re-discovers the routing in <30s.
* Off-season leagues (Bundesliga, Ligue 1) intermittently disappear
  from the upstream. Their slugs would return zero events during
  off-season — same behaviour as the rest of the API for off-season
  sports, so no special handling needed.

## Alternatives considered

1. **Per-competition fetches** — call `page=COMPETITION&competitionId=X`
   per league. Rejected: the endpoint returns HTTP 400 even with valid
   competitionIds (likely needs an additional auth/version param we
   couldn't reverse-engineer), and N+1 fetches against state tenants
   risk rate-limiting.

2. **Skip FD soccer entirely, rely on Action Network's FanDuel feed** —
   ANP's FD feed has thinner soccer coverage and AN throttles us
   harder than FD's own state tenants.

3. **Drop the `customPageId` path entirely; route everything through
   `eventTypeId`** — possible but high-risk. The `customPageId` path
   serves richer data for branded US sports pages (player props,
   blurbs, custom market groupings). Soccer has no equivalent branded
   page, so `eventTypeId` is just the right routing for it.

## References

* `scrapers/fanduel.py:SPORT_MAP` — slug-to-routing config.
* `scrapers/fanduel.py:_build_request_params` — dispatch.
* `scrapers/fanduel.py:_parse_response` — `competition_filter` slicing.
* `scripts/recon/fd_soccer_recon.py` — re-discovers eventTypeId map.
* `scripts/tests/check_fanduel_parse.py` — soccer routing assertions.
