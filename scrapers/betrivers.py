"""
BetRivers Sportsbook Scraper
Directly hits BetRivers' public sportsbook API for odds data.
Note: Sport filtering via query param is unreliable, so we fetch all events
and filter client-side by the 'sport' field in the response.
"""

import httpx
from datetime import datetime, timezone
from typing import List, Optional, Dict
from .models import (
    SportsbookSnapshot, Event, Market, Outcome, MarketType
)

SPORTSBOOK_NAME = "BetRivers"

BASE_URL = "https://il.betrivers.com/api/service/sportsbook/offering/listview/events"
CAGE_CODE = "847"

# Must include Referer and Origin headers or API returns 400
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://il.betrivers.com/sports",
    "Origin": "https://il.betrivers.com",
}

# Map BetRivers sport field values to our normalized names
SPORT_NORMALIZE = {
    "FOOTBALL": {"sport": "Football", "league": "NFL"},
    "BASKETBALL": {"sport": "Basketball", "league": "NBA"},
    "BASEBALL": {"sport": "Baseball", "league": "MLB"},
    "ICE_HOCKEY": {"sport": "Hockey", "league": "NHL"},
    "SOCCER": {"sport": "Soccer", "league": "Soccer"},
    "TENNIS": {"sport": "Tennis", "league": "Tennis"},
    "GOLF": {"sport": "Golf", "league": "Golf"},
    "BOXING": {"sport": "Boxing", "league": "Boxing"},
    "MMA": {"sport": "MMA", "league": "MMA"},
    "TABLE_TENNIS": {"sport": "Table Tennis", "league": "Table Tennis"},
    "VOLLEYBALL": {"sport": "Volleyball", "league": "Volleyball"},
    "HANDBALL": {"sport": "Handball", "league": "Handball"},
}

# Map our sport keys to BetRivers sport field values for filtering
OUR_SPORT_TO_BR = {
    "football": "FOOTBALL",
    "basketball": "BASKETBALL",
    "baseball": "BASEBALL",
    "hockey": "ICE_HOCKEY",
    "soccer": "SOCCER",
    "tennis": "TENNIS",
    "golf": "GOLF",
    "boxing": "BOXING",
    "mma": "MMA",
}


def _classify_market(market_name: str) -> MarketType:
    """Classify BetRivers market into our standard types."""
    name_lower = market_name.lower()
    if "moneyline" in name_lower or "money line" in name_lower or "to win" in name_lower:
        return MarketType.MONEYLINE
    elif "spread" in name_lower or "handicap" in name_lower or "point spread" in name_lower:
        return MarketType.SPREAD
    elif "total" in name_lower or "over/under" in name_lower or "over / under" in name_lower:
        return MarketType.TOTAL
    elif "player" in name_lower or "prop" in name_lower:
        return MarketType.PLAYER_PROP
    elif "future" in name_lower or "winner" in name_lower or "outright" in name_lower:
        return MarketType.FUTURES
    return MarketType.OTHER


def _safe_american_odds(raw_value) -> Optional[int]:
    """Safely parse American odds."""
    if raw_value is None:
        return None
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, float):
        return int(raw_value)
    if isinstance(raw_value, str):
        if raw_value == "EVEN":
            return 100
        try:
            return int(raw_value.replace("+", ""))
        except (ValueError, TypeError):
            return None
    return None


def _parse_event(raw_event: dict, sport: str, league: str) -> Optional[Event]:
    """Parse a single BetRivers event into our Event model."""
    participants = raw_event.get("participants", [])
    home_team = ""
    away_team = ""
    for p in participants:
        if p.get("home", False):
            home_team = p.get("name", "")
        else:
            away_team = p.get("name", "")

    # Parse start time
    start_time_str = raw_event.get("startTime", "")
    start_time = None
    if start_time_str and isinstance(start_time_str, str):
        try:
            start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    # Use competition name as league if available
    event_league = league
    competition = raw_event.get("competitionName", "")
    if competition:
        event_league = competition

    # Parse markets
    markets = []
    for bet_offer in raw_event.get("betOffers", []):
        market_name = bet_offer.get("betDescription", "")
        market_type = _classify_market(market_name)

        outcomes = []
        for raw_outcome in bet_offer.get("outcomes", []):
            outcome_name = raw_outcome.get("name", "") or raw_outcome.get("participantName", "")

            # American odds
            american_int = _safe_american_odds(raw_outcome.get("oddsAmerican"))

            # Decimal odds (BetRivers divides by 1000)
            odds_val = raw_outcome.get("odds", 0)
            try:
                decimal_val = float(odds_val) / 1000.0 if odds_val else None
            except (ValueError, TypeError):
                decimal_val = None

            # Line/handicap (BetRivers divides by 1000)
            line = raw_outcome.get("line", None)
            point_val = None
            if line is not None:
                try:
                    point_val = float(line) / 1000.0
                except (ValueError, TypeError):
                    point_val = None

            if american_int is not None or decimal_val is not None:
                outcomes.append(Outcome(
                    name=outcome_name,
                    price_american=american_int,
                    price_decimal=decimal_val,
                    point=point_val,
                ))

        if outcomes:
            markets.append(Market(
                market_type=market_type,
                name=market_name,
                outcomes=outcomes,
            ))

    if not markets:
        return None

    return Event(
        event_id=str(raw_event.get("id", "")),
        sport=sport,
        league=event_league,
        home_team=home_team,
        away_team=away_team,
        description=raw_event.get("name", ""),
        start_time=start_time,
        is_live=raw_event.get("state", "") == "STARTED",
        markets=markets,
    )


async def _fetch_all_events(client: httpx.AsyncClient, event_type: str = "prematch") -> List[dict]:
    """Fetch all events from BetRivers (no sport filter - it's unreliable)."""
    all_items = []
    page = 1
    max_pages = 10

    while page <= max_pages:
        params = {
            "cageCode": CAGE_CODE,
            "type": event_type,
            "page": str(page),
            "pageSize": "50",
        }
        try:
            resp = await client.get(BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

            items = data.get("items", [])
            if not items:
                break

            all_items.extend(items)

            paging = data.get("paging", {})
            total_pages = paging.get("totalPages", 1)
            if page >= total_pages:
                break
            page += 1
        except Exception as e:
            print(f"[BetRivers] Error fetching page {page} ({event_type}): {e}")
            break

    return all_items


def _group_events_by_sport(raw_items: List[dict]) -> Dict[str, List[dict]]:
    """Group raw BetRivers events by their sport field."""
    grouped = {}
    for item in raw_items:
        sport_code = item.get("sport", "UNKNOWN")
        if sport_code not in grouped:
            grouped[sport_code] = []
        grouped[sport_code].append(item)
    return grouped


async def fetch_sport(our_sport_key: str, client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    """Fetch odds for a specific sport from BetRivers."""
    close_client = False
    if client is None:
        client = httpx.AsyncClient(headers=HEADERS, timeout=30.0)
        close_client = True

    snapshots = []
    try:
        br_sport_code = OUR_SPORT_TO_BR.get(our_sport_key.lower())
        if not br_sport_code:
            return []

        sport_info = SPORT_NORMALIZE.get(br_sport_code, {"sport": our_sport_key.title(), "league": our_sport_key.title()})

        # Fetch all events and filter client-side
        all_items = await _fetch_all_events(client, "prematch")
        # Also get live events
        live_items = await _fetch_all_events(client, "live")
        all_items.extend(live_items)

        # Filter to our target sport
        sport_items = [item for item in all_items if item.get("sport", "") == br_sport_code]

        if not sport_items:
            return []

        # Parse events
        all_events = []
        for raw_event in sport_items:
            event = _parse_event(raw_event, sport_info["sport"], sport_info["league"])
            if event:
                all_events.append(event)

        now = datetime.now(timezone.utc)

        # Group by league
        league_events: Dict[str, List[Event]] = {}
        for ev in all_events:
            if ev.league not in league_events:
                league_events[ev.league] = []
            league_events[ev.league].append(ev)

        for league_name, events in league_events.items():
            snapshots.append(SportsbookSnapshot(
                sportsbook=SPORTSBOOK_NAME,
                sport=sport_info["sport"],
                league=league_name,
                fetched_at=now,
                events=events,
            ))

    except Exception as e:
        print(f"[BetRivers] Error fetching {our_sport_key}: {e}")
    finally:
        if close_client:
            await client.aclose()

    return snapshots


async def fetch_all() -> List[SportsbookSnapshot]:
    """Fetch odds for all sports from BetRivers."""
    snapshots = []
    async with httpx.AsyncClient(headers=HEADERS, timeout=30.0) as client:
        # Fetch all events once
        all_items = await _fetch_all_events(client, "prematch")
        live_items = await _fetch_all_events(client, "live")
        all_items.extend(live_items)

        # Group by sport
        grouped = _group_events_by_sport(all_items)
        now = datetime.now(timezone.utc)

        for sport_code, items in grouped.items():
            sport_info = SPORT_NORMALIZE.get(sport_code, {"sport": sport_code.title(), "league": sport_code.title()})

            all_events = []
            for raw_event in items:
                event = _parse_event(raw_event, sport_info["sport"], sport_info["league"])
                if event:
                    all_events.append(event)

            # Group by league
            league_events: Dict[str, List[Event]] = {}
            for ev in all_events:
                if ev.league not in league_events:
                    league_events[ev.league] = []
                league_events[ev.league].append(ev)

            for league_name, events in league_events.items():
                snapshots.append(SportsbookSnapshot(
                    sportsbook=SPORTSBOOK_NAME,
                    sport=sport_info["sport"],
                    league=league_name,
                    fetched_at=now,
                    events=events,
                ))

    return snapshots


async def fetch_nfl(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("football", client)

async def fetch_nba(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("basketball", client)

async def fetch_mlb(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("baseball", client)

async def fetch_nhl(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("hockey", client)