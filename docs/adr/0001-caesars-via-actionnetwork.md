# ADR-0001: Caesars served via ActionNetwork (not direct scraping)

**Status:** Accepted
**Date:** 2024
**Decision-maker:** Repo owner
**Supersedes:** N/A
**Superseded by:** N/A

## Context

The Sportsbook-API project's directive is to serve all major US sportsbooks
(DraftKings, Caesars, bet365, etc.) via direct scrapers we own — no external
paid odds providers (The Odds API, ZenRows, Scrapfly, etc.).

The standard pattern we use is:

1. **Playwright-prime** — spin up a real Chromium with stealth evasions, load
   the sportsbook homepage, let the bot-protection challenge complete, harvest
   the resulting cookies.
2. **curl_cffi-replay** — replay those cookies from a cheap HTTP client
   (curl_cffi for TLS fingerprint matching) against the JSON API endpoints.

This pattern works for DraftKings (Akamai Bot Manager) — see PR #3 / PR #4.
The same pattern was the planned approach for Caesars.

## Reconnaissance findings (Caesars)

Caesars's sportsbook frontend (`sportsbook.caesars.com`) calls a real backend
at `api.americanwagering.com/regions/us/locations/{state}/brands/czr/sb/{v3|v4}/...`.
That backend is fronted by **AWS WAF Bot Control**, which blocks our pattern
at two independent layers simultaneously:

### Layer 1 — CloudFront IP reputation

- Our Decodo residential ISP exits (`23.26.59.157` US-RCN, `96.126.164.129`
  CA-Rogers) are pre-banned. Caesars's CloudFront returns 403 before the
  request even reaches the application layer.
- DraftKings, by contrast, accepts the same Decodo exits without issue.

### Layer 2 — `aws-waf-token` is telemetry-bound, not replayable

Required headers on every odds XHR:

- `x-platform: cordova-desktop`
- `x-aws-waf-token: <token>`
- `Origin: https://sportsbook.caesars.com`

The `aws-waf-token` is minted by `challenge.js` running in the browser. It is
**single-use** and the signature is bound to per-request client telemetry
(timing, mouse, canvas, WebGL, audio fingerprints — collected continuously
during the session).

Empirical results, real Playwright Chrome with full puppeteer-stealth-equivalent
evasions on a clean sandbox DC IP:

- **37 of 39 XHRs return 403.** Only `/sb/features` and
  `/configs/sportsbook/{state}/splash` succeed — those are public-allowlist
  endpoints carrying no odds data.
- Token replay strategies tested — all returned 403:
  1. Header only
  2. Header + cookie jar
  3. Fresh token harvested from page-load XHR
  4. Networkidle wait before harvest
- `page.evaluate(fetch(...))` from inside the loaded SPA fails CORS preflight
  ("Failed to fetch") — Caesars's CSP blocks programmatic fetch from the page
  context.

Per Scrapfly's published research on AWS WAF Bot Control: tokens must be
refreshed by running `challenge.js` *inside* the bypass infrastructure with
live telemetry handling. Pure cookie/token replay does not work.

## Options considered

| # | Option | Verdict |
|---|---|---|
| 1 | **Keep ActionNetwork-served Caesars** (book_id 123, free aggregator) | ✅ **CHOSEN** |
| 2 | Add Scrapfly `asp=True` for Caesars only (~96% success, ~$50–150/mo) | ❌ External provider — violates project directive |
| 3 | Try a different residential proxy provider (Bright Data ISP, Oxylabs) | ❌ Solves Layer 1 but not Layer 2; also $100–300/mo |
| 4 | Build FlareSolverr-style WAF challenge solver locally | ❌ ~50% success, 1–2 weeks eng time, expensive per-request Chromium spin-up; still needs Layer 1 fix |
| 5 | ActionNetwork + UI lag indicator | Same as #1 with optional UX polish |

## Decision

**Caesars odds are served via the ActionNetwork aggregator** (book_id 123) in
`scrapers/actionnetwork.py`. This is a tactical exception to the "no outside
sources" directive, justified by:

- AWS WAF Bot Control specifically defeats the cookie-priming pattern that
  works elsewhere — this is a structural mismatch, not an implementation gap.
- Caesars is currently the only major US book using this configuration. DK is
  Akamai (beaten), bet365 is Imperva/Incapsula (likely beatable).
- Building a self-hosted WAF challenge solver for a single book is the wrong
  priority versus shipping the next book (bet365).

## Consequences

**Accepted:**

- Caesars odds carry whatever lag ActionNetwork has (typically 5–15 min vs
  real-time direct scrapes).
- We have a dependency on ActionNetwork's free public scoreboard endpoint for
  Caesars coverage. If ActionNetwork removes Caesars (book_id 123) or rate-limits
  us aggressively, Caesars goes dark until we revisit.
- Inline comment at `BOOK_MAP[123]` and module docstring in
  `scrapers/actionnetwork.py` reference this ADR so future contributors don't
  re-run the same recon.

## Revisit triggers

Revisit this decision if **any** of the following becomes true:

1. Bright Data ISP, Oxylabs ISP, or similar residential pool becomes affordable
   (<$50/mo for our volume) and field-tests show their ranges aren't pre-banned
   by Caesars's CloudFront. (This solves Layer 1; combine with #2 or #3 below.)
2. AWS WAF Bot Control config on `api.americanwagering.com` changes to allow
   token replay (test quarterly with a probe script).
3. A pure-Python `challenge.js` runner / open-source AWS WAF solver appears
   with documented >80% success rate.
4. ActionNetwork removes Caesars or starts rate-limiting our scraper —
   forcing the issue.

A probe script for re-testing belongs at `scripts/caesars_probe.py` (not yet
written; create when revisiting).

## References

- Scrapfly, "How to bypass AWS WAF" — https://scrapfly.io/blog/how-to-bypass-aws-waf/
- AWS docs, "Bot Control rule group" — https://docs.aws.amazon.com/waf/latest/developerguide/aws-managed-rule-groups-bot.html
- PR #3 (DK Akamai bypass) — `bfbef9c`
- PR #4 (DK proxy support) — `e9d1f45`
