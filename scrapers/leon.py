"""
Leon.bet Scraper
Leon.bet is a major international sportsbook with a rich public API.
Covers 39 sports with full market data including moneyline, spreads, totals.

API Pattern:
  - Sports catalog: /api-2/betline/sports?ctag=en-US&flags=urlv2
  - All events with odds: /api-2/betline/changes/all?ctag=en-US&vtag=&flags=urlv2
  - Event detail: /api-2/betline/event/all?ctag=en-US&eventId={id}&flags=urlv2
  - League events: /api-2/betline/events/all?ctag=en-US&league_id={id}&hideClosed=true&flags=urlv2
"""

import asyncio
import httpx
from datetime import datetime, timezone
from typing import List, Optional, Dict
from .models import SportsbookSnapshot, Event, Market, Outcome, MarketType

LEON_BASE = "https://leon.bet/api-2/betline"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

# Sport family -> (display_sport, display_league) and league keyword filters
SPORT_MAP = {
    "basketball_nba": {
        "family": "Basketball",
        "sport_label": "Basketball",
        "league_label": "NBA",
        "league_keywords": ["NBA"],
        "exclude_keywords": ["G League", "WNBA", "Women", "Draft", "Awards"],
    },
    "basketball_ncaab": {
        "family": "Basketball",
        "sport_label": "Basketball",
        "league_label": "NCAAB",
        "league_keywords": ["NCAA"],
        "exclude_keywords": ["Women"],
    },
    "football_nfl": {
        "family": "AmericanFootball",
        "sport_label": "Football",
        "league_label": "NFL",
        "league_keywords": ["NFL"],
        "exclude_keywords": ["Draft"],
    },
    "football_ncaaf": {
        "family": "AmericanFootball",
        "sport_label": "Football",
        "league_label": "NCAAF",
        "league_keywords": ["NCAA"],
        "exclude_keywords": [],
    },
    "baseball_mlb": {
        "family": "Baseball",
        "sport_label": "Baseball",
        "league_label": "MLB",
        "league_keywords": ["MLB"],
        "exclude_keywords": [],
    },
    "ice_hockey_nhl": {
        "family": "IceHockey",
        "sport_label": "Hockey",
        "league_label": "NHL",
        "league_keywords": ["NHL"],
        "exclude_keywords": ["AHL"],
    },
    "soccer": {
        "family": "Soccer",
        "sport_label": "Soccer",
        "league_label": "Soccer",
        "league_keywords": [],
        "exclude_keywords": ["Simulated", "Virtual"],
    },
    "soccer_epl": {
        "family": "Soccer",
        "sport_label": "Soccer",
        "league_label": "EPL",
        "league_keywords": ["Premier League", "England"],
        "exclude_keywords": ["Simulated", "Virtual", "Night Series"],
    },
    "tennis": {
        "family": "Tennis",
        "sport_label": "Tennis",
        "league_label": "Tennis",
        "league_keywords": [],
        "exclude_keywords": [],
    },
    "mma_ufc": {
        "family": "MMA",
        "sport_label": "MMA",
        "league_label": "UFC",
        "league_keywords": ["UFC"],
        "exclude_keywords": [],
    },
    "mma": {
        "family": "MMA",
        "sport_label": "MMA",
        "league_label": "MMA",
        "league_keywords": [],
        "exclude_keywords": [],
    },
    "boxing": {
        "family": "Boxing",
        "sport_label": "Boxing",
        "league_label": "Boxing",
        "league_keywords": [],
        "exclude_keywords": [],
    },
    "golf": {
        "family": "Golf",
        "sport_label": "Golf",
        "league_label": "Golf",
        "league_keywords": [],
        "exclude_keywords": [],
    },
    "cricket": {
        "family": "Cricket",
        "sport_label": "Cricket",
        "league_label": "Cricket",
        "league_keywords": [],
        "exclude_keywords": [],
    },
    "rugby_union": {
        "family": "RugbyUnion",
        "sport_label": "Rugby",
        "league_label": "Rugby Union",
        "league_keywords": [],
        "exclude_keywords": [],
    },
    "rugby_league": {
        "family": "RugbyLeague",
        "sport_label": "Rugby League",
        "league_label": "Rugby League",
        "league_keywords": [],
        "exclude_keywords": [],
    },
    "darts": {
        "family": "Darts",
        "sport_label": "Darts",
        "league_label": "Darts",
        "league_keywords": [],
        "exclude_keywords": [],
    },
    "table_tennis": {
        "family": "TableTennis",
        "sport_label": "Table Tennis",
        "league_label": "Table Tennis",
        "league_keywords": [],
        "exclude_keywords": [],
    },
    "volleyball": {
        "family": "Volleyball",
        "sport_label": "Volleyball",
        "league_label": "Volleyball",
        "league_keywords": [],
        "exclude_keywords": [],
    },
    "handball": {
        "family": "Handball",
        "sport_label": "Handball",
        "league_label": "Handball",
        "league_keywords": [],
        "exclude_keywords": [],
    },
    "esports": {
        "family": "ESport",
        "sport_label": "Esports",
        "league_label": "Esports",
        "league_keywords": [],
        "exclude_keywords": [],
    },
    "american_football_nfl": {
        "family": "AmericanFootball",
        "sport_label": "Football",
        "league_label": "NFL",
        "league_keywords": ["NFL"],
        "exclude_keywords": ["Draft"],
    },
    "american_football_ncaaf": {
        "family": "AmericanFootball",
        "sport_label": "Football",
        "league_label": "NCAAF",
        "league_keywords": ["NCAA"],
        "exclude_keywords": [],
    },
    "motor_sports": {
        "family": "Motorsport",
        "sport_label": "Motor Sports",
        "league_label": "Motor Sports",
        "league_keywords": [],
        "exclude_keywords": [],
    },
    "snooker": {
        "family": "Snooker",
        "sport_label": "Snooker",
        "league_label": "Snooker",
        "league_keywords": [],
        "exclude_keywords": [],
    },
    "cycling": {
        "family": "Cycling",
        "sport_label": "Cycling",
        "league_label": "Cycling",
        "league_keywords": [],
        "exclude_keywords": [],
    },
    "lacrosse": {
        "family": "Lacrosse",
        "sport_label": "Lacrosse",
        "league_label": "Lacrosse",
        "league_keywords": [],
        "exclude_keywords": [],
    },
    "aussie_rules": {
        "family": "AustralianRules",
        "sport_label": "Australian Rules",
        "league_label": "AFL",
        "league_keywords": [],
        "exclude_keywords": [],
    },
}


def _decimal_to_american(dec: float) -> Optional[int]:
    """Convert decimal odds to American format."""
    if not dec or dec <= 1.0:
        return None
    if dec >= 2.0:
        return int(round((dec - 1) * 100))
    return int(round(-100 / (dec - 1)))


def _parse_market(market_data: dict) -> Optional[Market]:
    """Parse a single market from Leon.bet event data."""
    name = market_data.get("name", "")
    runners = market_data.get("runners", [])
    if not runners:
        return None

    name_lower = name.lower()

    # Determine market type
    if name_lower in ["winner", "match winner", "moneyline", "money line",
                       "fight winner", "to win match", "1x2"]:
        return _build_market(MarketType.MONEYLINE, "Moneyline", runners)
    elif "handicap" in name_lower or "spread" in name_lower or "point spread" in name_lower:
        return _build_market(MarketType.SPREAD, "Spread", runners)
    elif name_lower in ["total", "total goals", "total points", "total runs",
                         "total games", "total rounds", "over/under"]:
        return _build_market(MarketType.TOTAL, "Total", runners)
    elif "winner" in name_lower and "draw" not in name_lower:
        return _build_market(MarketType.MONEYLINE, "Moneyline", runners)

    return None


def _build_market(mtype: MarketType, mname: str, runners: list) -> Optional[Market]:
    """Build a Market from Leon runners."""
    outcomes = []
    for r in runners:
        price = r.get("price")
        if not price or price <= 1.0:
            continue

        name = r.get("name", "?")
        tags = r.get("tags", [])

        # Determine spread/total point
        point = None
        if mtype == MarketType.SPREAD:
            # Extract handicap value from name (e.g., "Team (-3.5)")
            point = _extract_line(name, tags)
        elif mtype == MarketType.TOTAL:
            point = _extract_line(name, tags)
            # Normalize over/under labels
            if "over" in name.lower():
                name = "Over"
            elif "under" in name.lower():
                name = "Under"

        american = _decimal_to_american(price)
        outcomes.append(Outcome(
            name=name,
            price_american=american,
            price_decimal=round(price, 3),
            point=point,
        ))

    if len(outcomes) >= 2:
        return Market(market_type=mtype, name=mname, outcomes=outcomes)
    return None


def _extract_line(name: str, tags: list) -> Optional[float]:
    """Extract point/line value from runner name or tags."""
    import re
    # Try to extract number from parentheses: "Over (5.5)" or "Team (-3.5)"
    match = re.search(r'\(([+-]?\d+\.?\d*)\)', name)
    if match:
        try:
            return float(match.group(1))
        except:
            pass
    # Try plain number at end
    match = re.search(r'([+-]?\d+\.?\d*)$', name.strip())
    if match:
        try:
            val = float(match.group(1))
            if val != 0:
                return val
        except:
            pass
    return None


def _parse_event(ev_data: dict, sport_label: str, league_label: str) -> Optional[Event]:
    """Parse a single event from Leon.bet data."""
    name = ev_data.get("name", "")
    competitors = ev_data.get("competitors", [])

    if not name:
        return None

    # Extract home/away from competitors or name
    home = ""
    away = ""
    if competitors and len(competitors) >= 2:
        home = competitors[0].get("name", "")
        away = competitors[1].get("name", "")
    elif " - " in name:
        parts = name.split(" - ", 1)
        home = parts[0].strip()
        away = parts[1].strip()
    elif " vs " in name.lower():
        parts = name.lower().split(" vs ", 1)
        home = parts[0].strip().title()
        away = parts[1].strip().title()
    else:
        # Futures or single-competitor events - skip
        return None

    if not home or not away:
        return None

    event_id = str(ev_data.get("id", ""))
    kickoff = ev_data.get("kickoff")
    start_time = None
    if kickoff:
        try:
            # Leon uses epoch milliseconds
            start_time = datetime.fromtimestamp(kickoff / 1000, tz=timezone.utc)
        except:
            pass

    is_live = ev_data.get("liveStatus") == "Live" or ev_data.get("status") == "LIVE"

    # Parse markets
    markets = []
    for mkt_data in ev_data.get("markets", []):
        mkt = _parse_market(mkt_data)
        if mkt:
            markets.append(mkt)

    return Event(
        event_id=event_id,
        sport=sport_label,
        league=league_label,
        home_team=home,
        away_team=away,
        description=f"{away} @ {home}",
        start_time=start_time,
        is_live=is_live,
        markets=markets,
    )


async def fetch_sport(sport_key: str) -> List[SportsbookSnapshot]:
    """
    Fetch odds from Leon.bet for a given sport.
    
    Uses the changes/all endpoint for bulk data, filtered by sport family.
    Falls back to per-league fetching for specific league requests.
    """
    mapping = SPORT_MAP.get(sport_key)
    if not mapping:
        return []

    family = mapping["family"]
    sport_label = mapping["sport_label"]
    league_label = mapping["league_label"]
    league_keywords = mapping.get("league_keywords", [])
    exclude_keywords = mapping.get("exclude_keywords", [])

    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        # Use the changes/all endpoint - contains all events with market data
        url = f"{LEON_BASE}/changes/all?ctag=en-US&vtag=&flags=urlv2"
        try:
            resp = await client.get(url, headers=HEADERS)
            if resp.status_code != 200:
                return []
            data = resp.json()
        except Exception as e:
            print(f"[Leon] Error fetching changes: {e}")
            return []

        all_events = data.get("data", [])
        if not all_events:
            return []

        # Filter by sport family
        filtered = []
        for ev in all_events:
            # Get sport family from league -> sport -> family
            ev_league = ev.get("league", {})
            ev_sport = ev_league.get("sport", {}) if isinstance(ev_league, dict) else {}
            ev_family = ev_sport.get("family", "") if isinstance(ev_sport, dict) else ""
            ev_name = ev.get("name", "")
            ev_league_name = ev_league.get("name", "") if isinstance(ev_league, dict) else ""

            if ev_family != family:
                continue

            # Apply league keyword filter
            if league_keywords:
                matches_keyword = any(
                    kw.lower() in ev_league_name.lower() or kw.lower() in ev_name.lower()
                    for kw in league_keywords
                )
                if not matches_keyword:
                    continue

            # Apply exclude filter
            if exclude_keywords:
                excluded = any(
                    kw.lower() in ev_league_name.lower() or kw.lower() in ev_name.lower()
                    for kw in exclude_keywords
                )
                if excluded:
                    continue

            filtered.append(ev)

        # Parse events
        events = []
        for ev_data in filtered:
            ev = _parse_event(ev_data, sport_label, league_label)
            if ev:
                events.append(ev)

        # If we got events from changes/all but they have no markets,
        # fetch event details for up to 20 events
        events_needing_detail = [e for e in events if not e.markets]
        if events_needing_detail and len(events_needing_detail) <= 30:
            detail_tasks = []
            for ev in events_needing_detail[:20]:
                detail_tasks.append(_fetch_event_detail(client, ev))
            detail_results = await asyncio.gather(*detail_tasks, return_exceptions=True)
            for result in detail_results:
                if isinstance(result, Event):
                    # Replace in events list
                    for i, e in enumerate(events):
                        if e.event_id == result.event_id:
                            events[i] = result
                            break

    if not events:
        return []

    return [SportsbookSnapshot(
        sportsbook="Leon.bet",
        sport=sport_label,
        league=league_label,
        fetched_at=datetime.now(timezone.utc),
        events=events,
    )]


async def _fetch_event_detail(client: httpx.AsyncClient, event: Event) -> Event:
    """Fetch full event detail with all markets."""
    url = f"{LEON_BASE}/event/all?ctag=en-US&eventId={event.event_id}&flags=urlv2&hideClosed=true"
    try:
        resp = await client.get(url, headers=HEADERS)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict):
                markets = []
                for mkt_data in data.get("markets", []):
                    mkt = _parse_market(mkt_data)
                    if mkt:
                        markets.append(mkt)
                if markets:
                    event.markets = markets
    except Exception:
        pass
    return event