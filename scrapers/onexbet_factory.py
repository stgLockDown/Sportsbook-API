"""
1xBet Family Factory Scraper
=============================
Scrapes odds from 1xBet and its clones (BetWinner, Melbet, 1xBit, Linebet, MegaPari, 22Bet).
All use the same service-api/LineFeed/Get1x2_VZip endpoint with identical data structures.

Field mapping (compressed field names):
  Event Level:
    I   = Event ID
    O1  = Home team name (local)
    O1E = Home team name (English)
    O2  = Away team name (local)
    O2E = Away team name (English)
    L   = League name (local)
    LE  = League name (English)
    S   = Start time (Unix timestamp)
    SI  = Sport ID (1=Soccer, 2=Hockey, 3=Basketball, 4=Tennis, 5=Baseball, 6=Volleyball, 9=Boxing, 40=Esports)
    SE  = Sport name (English)

  Odds (E array and AE[].ME array):
    G = Market group:
        1  = 1X2 (Match Result)
        2  = Handicap (Asian)
        15 = Both Teams to Score
        17 = Over/Under (Total)
    T = Outcome type within group:
        G=1:  T1=Home, T2=Draw, T3=Away
        G=2:  T7=Home handicap, T8=Away handicap
        G=17: T9=Over, T10=Under
        G=15: T11=BTTS Yes, T12=BTTS No
    C  = Coefficient (decimal odds)
    CV = Coefficient as string
    P  = Point/line value (for handicap and total)
    CE = 1 if this is the "main" line
"""

import aiohttp
import asyncio
import json
from datetime import datetime, timezone
from typing import List, Optional
from .models import SportsbookSnapshot, Event, Market, Outcome, MarketType

# ─── Operators ───────────────────────────────────────────────────
ONEXBET_OPERATORS = {
    "1xbet": {
        "name": "1xBet",
        "base_url": "https://1xbet.com/service-api/LineFeed/Get1x2_VZip",
        "region": "Global/Asia/LatAm",
    },
    "betwinner": {
        "name": "BetWinner",
        "base_url": "https://betwinner.com/service-api/LineFeed/Get1x2_VZip",
        "region": "Global/Asia/LatAm",
    },
    "melbet": {
        "name": "Melbet",
        "base_url": "https://melbet.com/service-api/LineFeed/Get1x2_VZip",
        "region": "Asia/CIS",
    },
    "1xbit": {
        "name": "1xBit",
        "base_url": "https://1xbit.com/service-api/LineFeed/Get1x2_VZip",
        "region": "Crypto/Global",
    },
    "linebet": {
        "name": "Linebet",
        "base_url": "https://linebet.com/service-api/LineFeed/Get1x2_VZip",
        "region": "Asia/Bangladesh",
    },
    "megapari": {
        "name": "MegaPari",
        "base_url": "https://megapari.com/service-api/LineFeed/Get1x2_VZip",
        "region": "Global",
    },
    "22bet_direct": {
        "name": "22Bet (Direct)",
        "base_url": "https://22bet.com/service-api/LineFeed/Get1x2_VZip",
        "region": "Global/Africa",
    },
}

# 1xBet Sport ID mapping (verified from API):
#   1 = Football/Soccer
#   2 = Ice Hockey
#   3 = Basketball
#   4 = Tennis
#   5 = Baseball
#   6 = Volleyball
#   9 = Boxing/MMA
#   40 = Esports
SPORT_SLUG_TO_ID = {
    "soccer": 1,
    "basketball": 3,
    "baseball": 5,
    "ice-hockey": 2,
    "tennis": 4,
    "volleyball": 6,
    "mma": 9,
    "esports": 40,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _extract_main_odds(event_data: dict) -> dict:
    """
    Extract main market odds from event data.
    Returns dict: { (group, type) -> (decimal_odds, point) }
    Only keeps CE=1 (main line) entries when available.
    """
    odds = {}

    for outcome in event_data.get("E", []):
        g = outcome.get("G")
        t = outcome.get("T")
        c = outcome.get("C")
        p = outcome.get("P")
        ce = outcome.get("CE")

        if g is None or t is None or c is None:
            continue

        key = (g, t)
        if key not in odds or ce == 1:
            odds[key] = (c, p)

    return odds


def _build_markets(odds: dict, is_soccer: bool = True) -> List[Market]:
    """Build Market objects from extracted odds dict."""
    markets = []

    # 1X2 / Moneyline (G=1)
    home = odds.get((1, 1))
    draw = odds.get((1, 2))
    away = odds.get((1, 3))
    if home or away:
        outcomes = []
        if home:
            outcomes.append(Outcome(name="Home", price_decimal=home[0]))
        if draw and is_soccer:
            outcomes.append(Outcome(name="Draw", price_decimal=draw[0]))
        if away:
            outcomes.append(Outcome(name="Away", price_decimal=away[0]))
        markets.append(Market(
            market_type=MarketType.MONEYLINE,
            name="1X2" if (draw and is_soccer) else "Moneyline",
            outcomes=outcomes,
        ))

    # Handicap / Spread (G=2)
    home_hcap = odds.get((2, 7))
    away_hcap = odds.get((2, 8))
    if home_hcap and away_hcap:
        outcomes = [
            Outcome(name="Home", price_decimal=home_hcap[0], point=home_hcap[1]),
            Outcome(name="Away", price_decimal=away_hcap[0], point=away_hcap[1]),
        ]
        markets.append(Market(
            market_type=MarketType.SPREAD,
            name="Asian Handicap" if is_soccer else "Spread",
            outcomes=outcomes,
        ))

    # Over/Under / Total (G=17)
    over = odds.get((17, 9))
    under = odds.get((17, 10))
    if over and under:
        outcomes = [
            Outcome(name="Over", price_decimal=over[0], point=over[1]),
            Outcome(name="Under", price_decimal=under[0], point=under[1]),
        ]
        markets.append(Market(
            market_type=MarketType.TOTAL,
            name="Over/Under",
            outcomes=outcomes,
        ))

    return markets


async def fetch_onexbet(operator_key: str, sport_slug: str) -> Optional[SportsbookSnapshot]:
    """
    Fetch odds from a 1xBet family operator for a given sport.
    Uses aiohttp with ssl=False to avoid TLS fingerprinting issues.
    """
    if operator_key not in ONEXBET_OPERATORS:
        return None

    sport_id = SPORT_SLUG_TO_ID.get(sport_slug)
    if sport_id is None:
        return None

    op = ONEXBET_OPERATORS[operator_key]
    base_url = op["base_url"]
    book_name = op["name"]
    is_soccer = sport_slug == "soccer"

    url = f"{base_url}?sports={sport_id}&count=200&lng=en&mode=4"

    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=HEADERS, ssl=False) as resp:
                if resp.status != 200:
                    return SportsbookSnapshot(
                        sportsbook=book_name,
                        sport=sport_slug,
                        league="all",
                        fetched_at=datetime.now(timezone.utc),
                        events=[],
                    )

                text = await resp.text()
                data = json.loads(text)

                if not data.get("Success") or "Value" not in data:
                    return SportsbookSnapshot(
                        sportsbook=book_name,
                        sport=sport_slug,
                        league="all",
                        fetched_at=datetime.now(timezone.utc),
                        events=[],
                    )

                raw_events = data["Value"]
                events: List[Event] = []

                for ev in raw_events:
                    try:
                        home = ev.get("O1E") or ev.get("O1", "Unknown")
                        away = ev.get("O2E") or ev.get("O2", "Unknown")
                        league = ev.get("LE") or ev.get("L", "Unknown")
                        event_id = str(ev.get("I", ""))
                        start_ts = ev.get("S", 0)

                        start_time = None
                        if start_ts:
                            try:
                                start_time = datetime.fromtimestamp(start_ts, tz=timezone.utc)
                            except (ValueError, OSError):
                                pass

                        odds = _extract_main_odds(ev)
                        markets = _build_markets(odds, is_soccer=is_soccer)

                        if not markets:
                            continue

                        events.append(Event(
                            event_id=event_id,
                            sport=sport_slug,
                            league=league,
                            home_team=home,
                            away_team=away,
                            description=f"{home} vs {away}",
                            start_time=start_time,
                            is_live=False,
                            markets=markets,
                        ))
                    except Exception:
                        continue

                return SportsbookSnapshot(
                    sportsbook=book_name,
                    sport=sport_slug,
                    league="all",
                    fetched_at=datetime.now(timezone.utc),
                    events=events,
                )

    except Exception:
        return SportsbookSnapshot(
            sportsbook=book_name,
            sport=sport_slug,
            league="all",
            fetched_at=datetime.now(timezone.utc),
            events=[],
        )