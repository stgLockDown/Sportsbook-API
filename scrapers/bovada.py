"""
Bovada Sportsbook Scraper
Directly hits Bovada's public JSON API to pull odds for all sports.
"""

import httpx
from datetime import datetime, timezone
from typing import List, Optional
from .models import (
    SportsbookSnapshot, Event, Market, Outcome, MarketType
)

SPORTSBOOK_NAME = "Bovada"

BASE_URL = "https://www.bovada.lv/services/sports/event/v2/events/A/description"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# Bovada sport slugs -> our normalized sport/league names
SPORT_MAP = {
    "football": {"sport": "Football", "leagues": {
        "NFL": "NFL", "College Football": "NCAAF", "CFL": "CFL", "UFL": "UFL"
    }},
    "basketball": {"sport": "Basketball", "leagues": {
        "NBA": "NBA", "College Basketball": "NCAAB", "WNBA": "WNBA"
    }},
    "baseball": {"sport": "Baseball", "leagues": {
        "MLB": "MLB", "College Baseball": "College Baseball"
    }},
    "hockey": {"sport": "Hockey", "leagues": {
        "NHL": "NHL"
    }},
    "soccer": {"sport": "Soccer", "leagues": {}},
    "tennis": {"sport": "Tennis", "leagues": {}},
    "boxing": {"sport": "Boxing", "leagues": {}},
    "golf": {"sport": "Golf", "leagues": {}},
    "mma": {"sport": "MMA", "leagues": {
        "UFC": "UFC", "MMA": "MMA"
    }},
}


def _parse_market_type(key: str, description: str) -> MarketType:
    """Convert Bovada market key/description to our MarketType."""
    desc_lower = description.lower()
    if "moneyline" in desc_lower or key == "2W-12":
        return MarketType.MONEYLINE
    elif "spread" in desc_lower or "handicap" in desc_lower or key == "2W-HDP":
        return MarketType.SPREAD
    elif "total" in desc_lower or "over/under" in desc_lower or key == "2W-OU":
        return MarketType.TOTAL
    elif "prop" in desc_lower or "player" in desc_lower:
        return MarketType.PLAYER_PROP
    elif "future" in desc_lower or "winner" in desc_lower or "outright" in desc_lower:
        return MarketType.FUTURES
    return MarketType.OTHER


def _parse_event(raw_event: dict, sport: str, league: str) -> Event:
    """Parse a single Bovada event into our Event model."""
    competitors = raw_event.get("competitors", [])
    home_team = ""
    away_team = ""
    for comp in competitors:
        if comp.get("home"):
            home_team = comp.get("name", "")
        else:
            away_team = comp.get("name", "")

    start_ms = raw_event.get("startTime", 0)
    start_time = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc) if start_ms else None

    markets = []
    for display_group in raw_event.get("displayGroups", []):
        for raw_market in display_group.get("markets", []):
            period = raw_market.get("period", {})
            # Only include main period markets by default
            if not period.get("main", False) and not raw_market.get("description", "").startswith("Total"):
                # Include main markets + totals even if period isn't flagged main
                if period.get("main", False) is False and period.get("description", "") != "Game":
                    continue

            market_key = raw_market.get("key", "")
            market_desc = raw_market.get("description", "")
            market_type = _parse_market_type(market_key, market_desc)

            outcomes = []
            for raw_outcome in raw_market.get("outcomes", []):
                price = raw_outcome.get("price", {})
                american_str = price.get("american", "")
                try:
                    american_int = int(american_str.replace("+", "")) if american_str and american_str != "EVEN" else (100 if american_str == "EVEN" else None)
                except (ValueError, TypeError):
                    american_int = None

                decimal_str = price.get("decimal", "")
                try:
                    decimal_val = float(decimal_str) if decimal_str else None
                except (ValueError, TypeError):
                    decimal_val = None

                handicap_str = price.get("handicap", "")
                try:
                    point_val = float(handicap_str) if handicap_str else None
                except (ValueError, TypeError):
                    point_val = None

                outcomes.append(Outcome(
                    name=raw_outcome.get("description", ""),
                    price_american=american_int,
                    price_decimal=decimal_val,
                    point=point_val,
                ))

            if outcomes:
                markets.append(Market(
                    market_type=market_type,
                    name=market_desc,
                    outcomes=outcomes,
                ))

    return Event(
        event_id=str(raw_event.get("id", "")),
        sport=sport,
        league=league,
        home_team=home_team,
        away_team=away_team,
        description=raw_event.get("description", ""),
        start_time=start_time,
        is_live=raw_event.get("live", False),
        markets=markets,
    )


async def fetch_sport(sport_slug: str, client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    """Fetch all events for a Bovada sport slug (e.g., 'basketball', 'football')."""
    close_client = False
    if client is None:
        client = httpx.AsyncClient(headers=HEADERS, timeout=30.0)
        close_client = True

    snapshots = []
    try:
        url = f"{BASE_URL}/{sport_slug}"
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

        sport_info = SPORT_MAP.get(sport_slug, {"sport": sport_slug.title(), "leagues": {}})
        now = datetime.now(timezone.utc)

        for group in data:
            path = group.get("path", [])
            raw_events = group.get("events", [])

            # Determine league from path
            league_name = path[0].get("description", "Unknown") if path else "Unknown"
            sport_name = sport_info["sport"]

            events = []
            for raw_event in raw_events:
                try:
                    event = _parse_event(raw_event, sport_name, league_name)
                    if event.markets:  # Only include events with odds
                        events.append(event)
                except Exception:
                    continue

            if events:
                snapshots.append(SportsbookSnapshot(
                    sportsbook=SPORTSBOOK_NAME,
                    sport=sport_name,
                    league=league_name,
                    fetched_at=now,
                    events=events,
                ))
    except Exception as e:
        print(f"[Bovada] Error fetching {sport_slug}: {e}")
    finally:
        if close_client:
            await client.aclose()

    return snapshots


async def fetch_all() -> List[SportsbookSnapshot]:
    """Fetch odds for all supported sports from Bovada."""
    all_snapshots = []
    async with httpx.AsyncClient(headers=HEADERS, timeout=30.0) as client:
        for sport_slug in SPORT_MAP.keys():
            snapshots = await fetch_sport(sport_slug, client)
            all_snapshots.extend(snapshots)
    return all_snapshots


async def fetch_nfl(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("football", client)

async def fetch_nba(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("basketball", client)

async def fetch_mlb(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("baseball", client)

async def fetch_nhl(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("hockey", client)