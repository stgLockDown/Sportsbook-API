"""
FanDuel Sportsbook Scraper.

Hits FanDuel's public state-tenant SB API for odds data. The same payload
shape is served from each licensed-state subdomain (IL, NJ, PA, MI, …);
we use IL as the primary tenant and fall back to NJ/PA on failure for
redundancy.

Endpoint: GET sbapi.{state}.sportsbook.fanduel.com/api/content-managed-page

Two routing strategies, selected per-sport via SPORT_MAP[slug]["page"]:

  page=CUSTOM&customPageId={slug}    — legacy "branded" pages, used by
                                       all US team sports (NFL/NBA/MLB/NHL/
                                       NCAAF/NCAAB/WNBA/UFC/golf/tennis/boxing).
  page=SPORT&eventTypeId={int}       — Betfair-style super-sport pages,
                                       used by soccer (eventTypeId=1) which
                                       has no working customPageId.

Both strategies return the same payload shape:
  attachments.events  : { eventId  → { name, openDate, competitionId, … } }
  attachments.markets : { marketId → { eventId, marketName, marketType,
                                       runners: [{ runnerName, winRunnerOdds, … }] } }

For the SPORT path we additionally support an optional `competitionId`
filter on the slug config so a single fetch (e.g. eventTypeId=1) can be
sliced into per-league snapshots (EPL → 10932509, MLS → 141, UCL → 228).

Routes through the same Decodo US proxy used by DK and bet365 (since the
FD API is geofenced to US states).
"""
import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import List, Optional

import httpx

from .models import (
    Event, Market, MarketType, Outcome, SportsbookSnapshot,
)

logger = logging.getLogger(__name__)

SPORTSBOOK_NAME = "FanDuel"

# Tenant fallback chain. IL is primary because (a) it's the largest state
# tenant by event volume in our observed traffic and (b) it has the longest
# uptime track record. If IL fails, fall through to NJ then PA.
TENANTS = [
    "https://sbapi.il.sportsbook.fanduel.com/api/content-managed-page",
    "https://sbapi.nj.sportsbook.fanduel.com/api/content-managed-page",
    "https://sbapi.pa.sportsbook.fanduel.com/api/content-managed-page",
]

# FanDuel public API key. Same value across tenants; rotated rarely (last
# observed change Q3 2024).
API_KEY = "FhMFpcPWXMeyZxOx"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://sportsbook.fanduel.com/",
    "Origin": "https://sportsbook.fanduel.com",
}

# Per-attempt timeout. Total max wall-clock for a fetch_sport call:
# 3 attempts × 3 tenants × REQUEST_TIMEOUT = up to ~45s, but with
# exponential backoff between attempts that's more like ~30s typical.
REQUEST_TIMEOUT = 8.0
MAX_ATTEMPTS_PER_TENANT = 2

# FanDuel sport slug → routing config + normalized sport / league name.
#
# Each entry has at minimum {"sport", "league"}. Routing is selected by:
#   * customPageId      → uses page=CUSTOM&customPageId=<slug>   (default)
#   * event_type_id     → uses page=SPORT&eventTypeId=<int>
#
# When event_type_id is set, an optional competition_id filters the
# response to a single league/competition (FD calls this competitionId).
# When competition_id is None, all events under the eventTypeId are kept.
#
# Soccer uses eventTypeId=1 (the legacy Betfair convention FD inherits).
# customPageId=mls / epl / champions-league all return 404 as of 2026-Q2.
SPORT_MAP = {
    # ── customPageId path (page=CUSTOM) ─────────────────────────────────
    "nfl":              {"sport": "Football",   "league": "NFL"},
    "nba":              {"sport": "Basketball", "league": "NBA"},
    "mlb":              {"sport": "Baseball",   "league": "MLB"},
    "nhl":              {"sport": "Hockey",     "league": "NHL"},
    "ncaaf":            {"sport": "Football",   "league": "NCAAF"},
    "ncaab":            {"sport": "Basketball", "league": "NCAAB"},
    "wnba":             {"sport": "Basketball", "league": "WNBA"},
    "golf":             {"sport": "Golf",       "league": "PGA"},
    "ufc":              {"sport": "MMA",        "league": "UFC"},
    "boxing":           {"sport": "Boxing",     "league": "Boxing"},
    "tennis":           {"sport": "Tennis",     "league": "Tennis"},

    # ── eventTypeId path (page=SPORT) ───────────────────────────────────
    # Soccer super-sport: one fetch returns ~85 competitions / 140+ events.
    # Per-league slugs share the same upstream payload but filter to one
    # competitionId; consumers should call the most specific slug they need.
    #
    # Competition IDs are stable Betfair-derived identifiers and do not
    # rotate season-to-season. Verified against live FD payload 2026-Q2.
    # Off-season leagues (Bundesliga / Ligue 1) are not yet listed: they
    # only appear in the upstream payload while their season is active.
    # Add them by name match when needed (see _resolve_competition_id).
    "soccer":           {"sport": "Soccer", "league": "Soccer",
                         "event_type_id": 1},
    "epl":              {"sport": "Soccer", "league": "EPL",
                         "event_type_id": 1, "competition_id": 10932509},
    "mls":              {"sport": "Soccer", "league": "MLS",
                         "event_type_id": 1, "competition_id": 141},
    "champions-league": {"sport": "Soccer", "league": "Champions League",
                         "event_type_id": 1, "competition_id": 228},
    "europa-league":    {"sport": "Soccer", "league": "Europa Conference League",
                         "event_type_id": 1, "competition_id": 12375833},
    "la-liga":          {"sport": "Soccer", "league": "La Liga",
                         "event_type_id": 1, "competition_id": 117},
    "serie-a":          {"sport": "Soccer", "league": "Serie A",
                         "event_type_id": 1, "competition_id": 81},
    "eredivisie":       {"sport": "Soccer", "league": "Eredivisie",
                         "event_type_id": 1, "competition_id": 9404054},
    "liga-mx":          {"sport": "Soccer", "league": "Liga MX",
                         "event_type_id": 1, "competition_id": 5627174},
    "brazil-serie-a":   {"sport": "Soccer", "league": "Brazilian Serie A",
                         "event_type_id": 1, "competition_id": 13},
    "world-cup":        {"sport": "Soccer", "league": "FIFA World Cup",
                         "event_type_id": 1, "competition_id": 12469077},
    "nwsl":             {"sport": "Soccer", "league": "NWSL",
                         "event_type_id": 1, "competition_id": 12331715},
}


# ─── Market classification ─────────────────────────────────────────────
#
# Order matters. We check core market types first (moneyline, spread,
# total) so that a generic "Total Points" market doesn't get hijacked
# by a generic "points" keyword that's also used for player props.

# FanDuel marketType codes that are unambiguously core game markets.
# (Trumps any name-keyword match.)
_CORE_TYPE_CODES = {
    "MONEY_LINE":                MarketType.MONEYLINE,
    "MATCH_BETTING":             MarketType.MONEYLINE,
    "MATCH_HANDICAP_(2-WAY)":    MarketType.SPREAD,
    "MATCH_HANDICAP":            MarketType.SPREAD,
    "POINT_SPREAD":              MarketType.SPREAD,
    "RUN_LINE":                  MarketType.SPREAD,
    "PUCK_LINE":                 MarketType.SPREAD,
    "TOTAL_POINTS_(OVER/UNDER)": MarketType.TOTAL,
    "TOTAL_POINTS":              MarketType.TOTAL,
    "TOTAL_RUNS":                MarketType.TOTAL,
    "TOTAL_GOALS":               MarketType.TOTAL,
    "TOTAL":                     MarketType.TOTAL,
    "OVER_UNDER":                MarketType.TOTAL,
}

# Player-prop indicators (names contain these AND don't match core type).
# Note: prefer leading-word patterns where possible to avoid generic
# substrings like "to score" colliding with game props ("Both Teams to
# Score" → game_prop, not player_prop).
_PLAYER_PROP_KEYWORDS = (
    "player ", " player",
    "anytime goalscorer", "first goalscorer", "last goalscorer",
    "anytime touchdown scorer", "first touchdown scorer",
    "first basket", "first 3-pointer",
    "passing yards", "rushing yards", "receiving yards",
    "passing tds", "rushing tds", "receiving tds",
    "passing touchdowns", "rushing touchdowns", "receiving touchdowns",
    "completions", "interceptions thrown", "qb sacks",
    "tackles + assists", "first downs",
    "points + rebounds", "points + assists", "rebounds + assists",
    "p+r+a", "double double", "triple double",
    "made threes", "three pointers made", "3pt made",
    "blocks ", "steals ", "turnovers ",
    "total bases", "total hits ", "home runs ", "rbis", "strikeouts pitched",
    "shots on goal", "saves ",
    " aces", "double faults", "break points won",
    " - ",  # FD player-prop name pattern: "<Player> - <Stat>"
    # MLB FD-specific player-prop name patterns ("To Hit A Home Run",
    # "To Record A Hit", "To Record 2+ Total Bases", …):
    "to hit a", "to record",
)

# Team-prop keywords (team-level, but not core h2h/spread/total).
_TEAM_PROP_KEYWORDS = (
    "team to score first", "team to score last", "team to score most",
    "team total", "team points",
    "first team to ", "race to ", "winning margin",
    "highest scoring quarter", "highest scoring half",
)

# Game-prop keywords (game-state markets).
_GAME_PROP_KEYWORDS = (
    "both teams to score", "btts",
    "draw no bet", "double chance",
    "will the game go to overtime", "go to ot",
    "first half", "second half", "first quarter", "second quarter",
    "third quarter", "fourth quarter",
    "first period", "second period", "third period",
    "first inning", "5 innings", "first 5 innings",
    "exact score", "correct score",
)

# Futures keywords.
_FUTURES_KEYWORDS = (
    "to win the", "outright", "championship", "mvp",
    "rookie of the year", "coach of the year",
    "season wins", "regular season wins", "win total",
    "world series", "super bowl", "stanley cup",
    "to make the playoffs", "to miss the playoffs",
    "specials", "futures",
)


def _classify_market(market_type_raw: str, market_name: str) -> MarketType:
    """Categorize a FanDuel market.

    Decision order:
      1. Core type code (MONEY_LINE, TOTAL_POINTS_…, …) — definitive.
      2. FD typeCode prefix patterns (PLAYER_, _PLAYER_, …) — strong signal.
      3. Futures keywords (typically standalone tournament events).
      4. Player-prop keywords (highest specificity for non-core).
      5. Team-prop keywords.
      6. Game-prop keywords.
      7. Fallback to MarketType.OTHER.
    """
    name_lc = (market_name or "").lower()
    type_uc = (market_type_raw or "").upper()

    # 1. Core type code — trumps name. This fixes "Total Points" being
    # mis-classified as PLAYER_PROP because of the bare "points" keyword.
    if type_uc in _CORE_TYPE_CODES:
        return _CORE_TYPE_CODES[type_uc]

    # Some core markets only have the name to go on (no useful type).
    if "moneyline" in name_lc or "money line" in name_lc:
        return MarketType.MONEYLINE
    if "spread" in name_lc or "handicap" in name_lc or "run line" in name_lc or "puck line" in name_lc:
        return MarketType.SPREAD
    if name_lc.startswith("total ") or "over/under" in name_lc or "(over/under)" in name_lc:
        # Disambiguate: if a player name is in the title, it's a prop
        # ("LeBron James - Total Points"). Detect by checking for
        # title-cased multi-word substrings that aren't team names.
        if "player" in name_lc or " - " in (market_name or ""):
            return MarketType.PLAYER_PROP
        return MarketType.TOTAL

    # 2. FD type-code prefix signals.
    if "PLAYER_" in type_uc or type_uc.endswith("_SPECIALS"):
        return MarketType.PLAYER_PROP
    if type_uc.endswith("_FUTURES") or "_AWARDS" in type_uc or "_MVP" in type_uc:
        return MarketType.FUTURES
    if type_uc.endswith("_TEAM_TOTAL") or "_TEAM_" in type_uc:
        return MarketType.TEAM_PROP

    # 3. Futures.
    if any(kw in name_lc for kw in _FUTURES_KEYWORDS):
        return MarketType.FUTURES

    # 4. Player props.
    if any(kw in name_lc for kw in _PLAYER_PROP_KEYWORDS):
        return MarketType.PLAYER_PROP

    # 5. Team props.
    if any(kw in name_lc for kw in _TEAM_PROP_KEYWORDS):
        return MarketType.TEAM_PROP

    # 6. Game props.
    if any(kw in name_lc for kw in _GAME_PROP_KEYWORDS):
        return MarketType.GAME_PROP

    return MarketType.OTHER


def _safe_american_odds(raw_value) -> Optional[int]:
    """Coerce FanDuel's mixed odds representations to int American odds.

    FanDuel returns:
      * `int` directly for most markets
      * `float` occasionally
      * the string "EVEN" for +100
      * a string like "+150" or "-110"
    """
    if raw_value is None:
        return None
    if isinstance(raw_value, bool):
        return None  # guard against True/False being treated as 1/0
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, float):
        return int(raw_value)
    if isinstance(raw_value, str):
        v = raw_value.strip().upper()
        if v == "EVEN" or v == "EVS":
            return 100
        try:
            return int(v.replace("+", ""))
        except (ValueError, TypeError):
            return None
    return None


def _parse_start_time(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _split_event_name(ev_name: str) -> tuple:
    """Split FD event name into (away, home).

    FD uses "Away @ Home" for US sports and "Home v Away" for soccer.
    Returns ("", ev_name) for futures/specials with no separator.
    """
    if not ev_name:
        return ("", "")
    if " @ " in ev_name:
        away, home = ev_name.split(" @ ", 1)
        return away.strip(), home.strip()
    if " v " in ev_name:
        # FD soccer convention: "Home v Away"
        home, away = ev_name.split(" v ", 1)
        return away.strip(), home.strip()
    if " vs " in ev_name:
        home, away = ev_name.split(" vs ", 1)
        return away.strip(), home.strip()
    return ("", "")


def _build_request_params(sport_info: dict, sport_slug: str) -> dict:
    """Return the query params dict for the content-managed-page call.

    Selects between page=CUSTOM (legacy customPageId path) and page=SPORT
    (eventTypeId path used by soccer) based on what's set in sport_info.
    """
    if "event_type_id" in sport_info:
        return {
            "page": "SPORT",
            "eventTypeId": sport_info["event_type_id"],
            "_ak": API_KEY,
        }
    return {
        "page": "CUSTOM",
        "customPageId": sport_slug,
        "_ak": API_KEY,
    }


def _parse_response(
    data: dict,
    sport: str,
    league: str,
    competition_filter: Optional[int] = None,
) -> List[Event]:
    """Parse a content-managed-page payload into our Event models.

    The payload structure is:
        {
          "attachments": {
            "events":  { "<eventId>": { name, openDate, … } },
            "markets": { "<marketId>": { eventId, marketName, marketType, runners: [...] } }
          }
        }
    """
    attachments = data.get("attachments", {}) or {}
    raw_events = attachments.get("events", {}) or {}
    raw_markets = attachments.get("markets", {}) or {}

    # Group markets by eventId so we don't scan all markets per event.
    event_markets: dict = {}
    for mkt in raw_markets.values():
        eid = str(mkt.get("eventId", ""))
        if eid:
            event_markets.setdefault(eid, []).append(mkt)

    events: List[Event] = []
    for eid, ev in raw_events.items():
        # When fetching a super-sport page (e.g. eventTypeId=1 = Soccer),
        # filter to a single competition so each per-league slug returns
        # only its own fixtures.
        if competition_filter is not None:
            ev_comp = ev.get("competitionId")
            if ev_comp != competition_filter:
                continue

        ev_name = ev.get("name", "") or ""
        start_time = _parse_start_time(ev.get("openDate", ""))

        # Drop far-future placeholder events (FD sometimes returns
        # year-2099 markers for season-long futures we already cover
        # via name).
        if start_time and start_time.year > 2090:
            continue

        # Prefer FD's explicit homeTeam / awayTeam fields when present
        # (game events have them). Fall back to splitting event name.
        home_team = (ev.get("homeTeam") or "").strip() or ""
        away_team = (ev.get("awayTeam") or "").strip() or ""
        if not (home_team or away_team):
            away_team, home_team = _split_event_name(ev_name)

        markets: List[Market] = []
        for raw_mkt in event_markets.get(str(eid), []):
            mkt_name = raw_mkt.get("marketName", "") or ""
            mkt_type_raw = raw_mkt.get("marketType", "") or ""
            market_type = _classify_market(mkt_type_raw, mkt_name)

            outcomes: List[Outcome] = []
            for runner in raw_mkt.get("runners", []) or []:
                runner_name = (runner.get("runnerName") or "").strip()
                odds_data = runner.get("winRunnerOdds", {}) or {}

                raw_american = (
                    odds_data.get("americanDisplayOdds", {}) or {}
                ).get("americanOdds")
                american_int = _safe_american_odds(raw_american)
                if american_int is None:
                    # Some runners have `runnerStatus = "REMOVED"` and no
                    # price — skip them.
                    continue

                # Decimal odds (true odds, not display).
                decimal_val: Optional[float] = None
                true_odds = (odds_data.get("trueOdds") or {}).get("decimalOdds") or {}
                if true_odds:
                    try:
                        raw_decimal = true_odds.get("decimalOdds", 0)
                        decimal_val = float(raw_decimal) if raw_decimal else None
                    except (ValueError, TypeError):
                        decimal_val = None

                # Handicap / line.
                point_val: Optional[float] = None
                hcap = runner.get("handicap")
                if hcap is not None:
                    try:
                        point_val = float(hcap)
                    except (ValueError, TypeError):
                        point_val = None

                outcomes.append(Outcome(
                    name=runner_name or "(?)",
                    price_american=american_int,
                    price_decimal=decimal_val,
                    point=point_val,
                ))

            if outcomes:
                markets.append(Market(
                    market_type=market_type,
                    name=mkt_name,
                    outcomes=outcomes,
                ))

        if markets:
            events.append(Event(
                event_id=str(eid),
                sport=sport,
                league=league,
                home_team=home_team or ev_name,
                away_team=away_team,
                description=ev_name,
                start_time=start_time,
                is_live=bool(ev.get("inPlay", False)),
                markets=markets,
            ))

    return events


# ─── HTTP fetch with retry + tenant fallback ──────────────────────────

async def _fetch_one(
    client: httpx.AsyncClient,
    url: str,
    sport_slug: str,
    sport_info: dict,
) -> Optional[dict]:
    """Single GET attempt. Returns parsed JSON on 200, None otherwise."""
    params = _build_request_params(sport_info, sport_slug)
    try:
        resp = await client.get(url, params=params, timeout=REQUEST_TIMEOUT)
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        logger.warning("FanDuel GET %s sport=%s network error: %s", url, sport_slug, exc)
        return None
    except Exception as exc:
        logger.warning("FanDuel GET %s sport=%s unexpected error: %s", url, sport_slug, exc)
        return None

    if resp.status_code != 200:
        logger.warning(
            "FanDuel %s sport=%s HTTP %d", url, sport_slug, resp.status_code,
        )
        return None
    try:
        return resp.json()
    except Exception as exc:
        logger.warning("FanDuel %s sport=%s JSON decode error: %s", url, sport_slug, exc)
        return None


async def _fetch_with_fallback(
    client: httpx.AsyncClient,
    sport_slug: str,
    sport_info: dict,
) -> Optional[dict]:
    """Try each tenant in order with limited retries per tenant.

    Returns the first non-empty payload; None if all tenants exhausted.
    """
    last_error_payload: Optional[dict] = None
    for tenant_url in TENANTS:
        for attempt in range(MAX_ATTEMPTS_PER_TENANT):
            data = await _fetch_one(client, tenant_url, sport_slug, sport_info)
            if data is not None:
                # Treat the 'error: true' response shape as a soft failure.
                if isinstance(data, dict) and data.get("error") is True:
                    last_error_payload = data
                    break  # don't retry this tenant; move on
                return data
            # Backoff before retry on the same tenant.
            if attempt < MAX_ATTEMPTS_PER_TENANT - 1:
                jitter = random.uniform(0.1, 0.3)
                await asyncio.sleep(0.5 + jitter)
        # Move to next tenant.
        logger.info(
            "FanDuel tenant %s exhausted for sport=%s; trying next tenant",
            tenant_url, sport_slug,
        )
    if last_error_payload is not None:
        logger.warning("FanDuel: all tenants returned error for sport=%s", sport_slug)
    return None


async def fetch_sport(
    sport_slug: str, client: Optional[httpx.AsyncClient] = None,
) -> List[SportsbookSnapshot]:
    """Fetch odds for one FanDuel sport page.

    Routes through the US proxy if configured (US_PROXY_URL env). Falls
    back across IL → NJ → PA tenants on per-tenant failure.
    """
    close_client = False
    if client is None:
        from ._proxy import get_client_kwargs
        client = httpx.AsyncClient(
            headers=HEADERS, timeout=REQUEST_TIMEOUT, **get_client_kwargs("US"),
        )
        close_client = True

    try:
        sport_info = SPORT_MAP.get(sport_slug, {
            "sport": sport_slug.upper(), "league": sport_slug.upper(),
        })
        data = await _fetch_with_fallback(client, sport_slug, sport_info)
        if not data:
            logger.error("FanDuel: all tenants failed for sport=%s", sport_slug)
            return []

        events = _parse_response(
            data,
            sport_info["sport"],
            sport_info["league"],
            competition_filter=sport_info.get("competition_id"),
        )
        if not events:
            return []

        return [SportsbookSnapshot(
            sportsbook=SPORTSBOOK_NAME,
            sport=sport_info["sport"],
            league=sport_info["league"],
            fetched_at=datetime.now(timezone.utc),
            events=events,
        )]
    finally:
        if close_client:
            await client.aclose()


async def fetch_all() -> List[SportsbookSnapshot]:
    """Fetch every supported FanDuel sport in sequence."""
    from ._proxy import get_client_kwargs
    out: List[SportsbookSnapshot] = []
    async with httpx.AsyncClient(
        headers=HEADERS, timeout=REQUEST_TIMEOUT, **get_client_kwargs("US"),
    ) as client:
        for slug in SPORT_MAP:
            try:
                out.extend(await fetch_sport(slug, client))
            except Exception as exc:
                logger.exception("FanDuel fetch_all sport=%s crashed: %s", slug, exc)
    return out


# ─── Backwards-compatible per-sport convenience wrappers ──────────────

async def fetch_nfl(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("nfl", client)


async def fetch_nba(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("nba", client)


async def fetch_mlb(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("mlb", client)


async def fetch_nhl(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("nhl", client)


async def fetch_ncaaf(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("ncaaf", client)


async def fetch_ncaab(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("ncaab", client)


async def fetch_wnba(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("wnba", client)


# ─── Soccer convenience wrappers ────────────────────────────────────────
# These all hit the same upstream payload (eventTypeId=1) but each filters
# to a single competition. If you need every soccer event in one shot,
# call fetch_sport("soccer", …) instead.

async def fetch_soccer(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("soccer", client)


async def fetch_epl(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("epl", client)


async def fetch_mls(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("mls", client)


async def fetch_champions_league(
    client: Optional[httpx.AsyncClient] = None,
) -> List[SportsbookSnapshot]:
    return await fetch_sport("champions-league", client)

