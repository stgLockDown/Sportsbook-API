"""
DraftKings scraper — Akamai-bypass via Playwright cookie priming.

DraftKings' public API (`sportsbook-nash.draftkings.com`) is fronted by
Akamai Bot Manager which 403s every direct httpx/curl_cffi call regardless
of TLS impersonation or proxy.

Strategy:
  1. A background task (`_dk_session`) primes a real Chromium browser every
     5 min, harvesting Akamai's `_abck`/`bm_sz`/`STH`/`_dd_s` cookies.
  2. We then call DK's content API endpoint
     `/sites/{site}/api/sportscontent/controldata/league/leagueSubcategory/v1/markets`
     via curl_cffi with those cookies. Akamai accepts the cookies for ~7 min.
  3. The cheap call returns the same JSON the official SPA receives:
     {sports, leagues, events, markets, selections}.

If Playwright is unavailable or priming fails, this scraper returns an
empty list rather than crashing the API server — degrades gracefully.

Keeps the same public interface `fetch_sport(sport)` so the aggregator does
not need to change.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from .models import SportsbookSnapshot, Event, Market, Outcome, MarketType
from . import _dk_session

logger = logging.getLogger("scraper.draftkings")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
SITE_CODE = "US-OR-SB"  # Any DK state site works; OR is what the SPA uses

NASH_BASE = "https://sportsbook-nash.draftkings.com"

# Sport -> (DK leagueId, default subcategoryId for "Game Lines"/main markets)
# Each league has a different subcategoryId for the Featured/Game Lines tab.
# These IDs were captured live from DK's SPA XHR traffic.
SPORT_LEAGUE: Dict[str, tuple[str, str]] = {
    "nba":    ("42648", "4511"),
    "nfl":    ("88808", "10500"),
    "mlb":    ("84240", "4519"),
    "nhl":    ("42133", "4525"),
    "ncaab":  ("92483", "4511"),  # college basketball reuses NBA subcat
    "ncaaf":  ("87637", "10500"), # college football reuses NFL subcat
    "soccer": ("40253", "4511"),  # EPL — DK splits soccer by competition
    "tennis": ("92000", "4511"),
    "mma":    ("9034",  "4511"),
    "golf":   ("13",    "4511"),
    "boxing": ("9035",  "4511"),
    "wnba":   ("94682", "4511"),
}

# Default subcategory if mapping above doesn't have one.
DEFAULT_SUBCATEGORY = "4511"


def _classify_market(name: str) -> MarketType:
    """Classify market name into our canonical MarketType."""
    n = (name or "").lower()
    if "moneyline" in n or n == "match winner":
        return MarketType.MONEYLINE
    if any(s in n for s in ("spread", "run line", "puck line", "handicap", "point spread")):
        return MarketType.SPREAD
    if "total" in n or "over/under" in n:
        return MarketType.TOTAL
    if any(s in n for s in ("player", "points", "rebounds", "assists", "strikeouts",
                            "passing", "rushing", "receiving", "to score", "ace")):
        return MarketType.PLAYER_PROP
    if "team total" in n or "first half team" in n:
        return MarketType.TEAM_PROP
    if any(s in n for s in ("winner", "championship", "to win", "season", "futures")):
        return MarketType.FUTURES
    return MarketType.OTHER


def _parse_american(s: Any) -> Optional[int]:
    """Parse '+110', '-200', '110', '−108' (unicode minus) into int."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return int(s)
    s = str(s).strip().replace("\u2212", "-").replace("−", "-").replace("+", "")
    try:
        return int(s)
    except ValueError:
        return None


def _american_to_decimal(am: int) -> float:
    if am > 0:
        return round(1 + am / 100.0, 4)
    return round(1 + 100.0 / abs(am), 4)


def _fetch_dk_markets(
    jar: Dict[str, str],
    league_id: str,
    subcat_id: str = DEFAULT_SUBCATEGORY,
) -> Optional[dict]:
    """
    Synchronous (blocking) call via curl_cffi. Run inside `asyncio.to_thread`.
    Returns parsed JSON dict or None on failure.
    """
    try:
        from curl_cffi import requests as cf
    except ImportError:
        logger.error("curl_cffi not installed — cannot scrape DK")
        return None

    url = f"{NASH_BASE}/sites/{SITE_CODE}/api/sportscontent/controldata/league/leagueSubcategory/v1/markets"
    params = {
        "isBatchable": "false",
        "templateVars": f"{league_id},{subcat_id}",
        "eventsQuery": (
            f"$filter=leagueId eq '{league_id}' AND "
            f"clientMetadata/Subcategories/any(s: s/Id eq '{subcat_id}')"
        ),
        "marketsQuery": (
            f"$filter=clientMetadata/subCategoryId eq '{subcat_id}' AND "
            f"tags/all(t: t ne 'SportcastBetBuilder')"
        ),
        "include": "Events",
        "entity": "events",
    }
    headers = {
        "User-Agent": UA,
        "Accept": "*/*",
        "Accept-Language": "en-US",
        "Origin": "https://sportsbook.draftkings.com",
        "Referer": "https://sportsbook.draftkings.com/",
        "x-client-feature": "leagueSubcategory",
        "x-client-name": "web",
        "x-client-page": "league",
        "x-client-version": "2621.3.1.5",
        "sec-fetch-site": "same-site",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "sec-ch-ua": '"Chromium";v="148", "Not/A)Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
    }
    try:
        r = cf.get(
            url,
            params=params,
            headers=headers,
            cookies=jar,
            impersonate="chrome120",
            timeout=15,
            allow_redirects=False,
        )
        if r.status_code != 200:
            logger.warning("DK %s markets returned %s (cookies stale?)", league_id, r.status_code)
            return None
        return r.json()
    except Exception as e:
        logger.exception("DK fetch error for league %s: %s", league_id, e)
        return None


def _build_events(raw: dict, sport: str) -> List[Event]:
    """Convert the DK markets/selections payload into our Event model."""
    if not raw:
        return []
    events_raw = raw.get("events", [])
    markets_raw = raw.get("markets", [])
    selections_raw = raw.get("selections", [])
    leagues_raw = raw.get("leagues", [])

    league_name = sport.upper()
    if leagues_raw:
        league_name = leagues_raw[0].get("name", league_name)

    # Index selections by marketId for O(1) attach
    sel_by_market: Dict[str, List[dict]] = {}
    for s in selections_raw:
        sel_by_market.setdefault(s.get("marketId"), []).append(s)

    # Index markets by eventId
    markets_by_event: Dict[str, List[dict]] = {}
    for m in markets_raw:
        markets_by_event.setdefault(m.get("eventId"), []).append(m)

    out: List[Event] = []
    for ev in events_raw:
        eid = str(ev.get("id", ""))
        if not eid:
            continue
        # participants[] holds Home/Away with venueRole
        parts = ev.get("participants", [])
        home, away = "", ""
        for p in parts:
            if p.get("venueRole") == "Home":
                home = p.get("name", "")
            elif p.get("venueRole") == "Away":
                away = p.get("name", "")
        # Fallback: name pattern "AWAY @ HOME"
        if not (home and away) and "@" in (ev.get("name") or ""):
            try:
                away, home = [s.strip() for s in ev["name"].split("@", 1)]
            except Exception:
                pass

        # Start time
        start_time: Optional[datetime] = None
        s_str = ev.get("startEventDate") or ev.get("startTime")
        if s_str:
            # DK uses .NET-style "2026-05-24T00:10:00.0000000Z" — Python can't
            # parse 7-digit microseconds, trim to 6.
            s_clean = s_str.replace("Z", "+00:00")
            # collapse fractional > 6 digits
            import re
            s_clean = re.sub(r"\.(\d{6})\d+", r".\1", s_clean)
            try:
                start_time = datetime.fromisoformat(s_clean)
            except Exception:
                pass

        is_live = bool(ev.get("isLive", False))

        # Build markets
        ev_markets: List[Market] = []
        for m in markets_by_event.get(eid, []):
            m_name = m.get("name", "")
            mtype = _classify_market(m_name)
            outcomes: List[Outcome] = []
            for sel in sel_by_market.get(m.get("id"), []):
                label = sel.get("label", "")
                disp = sel.get("displayOdds") or {}
                am = _parse_american(disp.get("american"))
                if am is None:
                    continue
                # Try to extract point/line from selection
                point: Optional[float] = None
                # DK puts the line in different fields depending on market
                for k in ("points", "line", "handicap"):
                    v = sel.get(k)
                    if v is not None:
                        try:
                            point = float(v)
                            break
                        except Exception:
                            pass
                # For Spreads / Totals, DK encodes the line in label like "+2.5" or "Over 214.5"
                if point is None and label:
                    import re
                    mm = re.search(r"[+-−]?\d+\.?\d*", label.replace("\u2212", "-"))
                    if mm:
                        try:
                            point = float(mm.group(0))
                        except Exception:
                            pass

                outcomes.append(Outcome(
                    name=label,
                    price_american=am,
                    price_decimal=_american_to_decimal(am),
                    point=point,
                ))

            if outcomes:
                ev_markets.append(Market(
                    market_type=mtype,
                    name=m_name,
                    outcomes=outcomes,
                ))

        if not ev_markets:
            continue

        out.append(Event(
            event_id=eid,
            sport=sport,
            league=league_name,
            home_team=home or ev.get("name", ""),
            away_team=away,
            description=ev.get("name", f"{away} @ {home}".strip(" @")),
            start_time=start_time,
            is_live=is_live,
            markets=ev_markets,
        ))
    return out


async def fetch_sport(sport: str) -> List[SportsbookSnapshot]:
    """
    Fetch DraftKings odds for a sport via the Akamai-bypass session.
    Returns [] gracefully if the cookie session is not yet primed or if
    Playwright is unavailable.
    """
    sport = (sport or "").lower()
    mapping = SPORT_LEAGUE.get(sport)
    if not mapping:
        return []
    league_id, subcat_id = mapping

    jar = await _dk_session.get_jar()
    if not jar:
        # Session not ready (Playwright down or first-prime in flight)
        return []

    # The actual HTTP call is sync (curl_cffi). Run it off the event loop.
    raw = await asyncio.to_thread(_fetch_dk_markets, jar, league_id, subcat_id)
    if not raw:
        return []

    events = _build_events(raw, sport)
    if not events:
        return []

    return [SportsbookSnapshot(
        sportsbook="DraftKings",
        sport=sport,
        league=events[0].league if events else sport.upper(),
        events=events,
        fetched_at=datetime.now(timezone.utc),
    )]
