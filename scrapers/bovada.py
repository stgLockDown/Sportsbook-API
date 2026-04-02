"""
Bovada Sportsbook Scraper
Directly hits Bovada's public JSON API to pull odds for all sports.
Updated to capture ALL available markets including player props, alternate lines, game props.
"""

import httpx
from datetime import datetime, timezone
from typing import List, Optional
from .models import (
    SportsbookSnapshot, Event, Market, Outcome, MarketType
)

SPORTSBOOK_NAME = "Bovada"

# Updated to working endpoint pattern
BASE_URL = "https://www.bovada.lv/services/sports/event/coupon/events/A/description"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# Bovada sport/league slugs -> our normalized sport/league names
SPORT_LEAGUE_MAP = {
    "basketball/nba": {"sport": "Basketball", "league": "NBA"},
    "basketball/wnba": {"sport": "Basketball", "league": "WNBA"},
    "basketball/ncaa": {"sport": "Basketball", "league": "NCAAB"},
    "football/nfl": {"sport": "Football", "league": "NFL"},
    "football/ncaa": {"sport": "Football", "league": "NCAAF"},
    "football/cfl": {"sport": "Football", "league": "CFL"},
    "baseball/mlb": {"sport": "Baseball", "league": "MLB"},
    "hockey/nhl": {"sport": "Hockey", "league": "NHL"},
    "mma/ufc": {"sport": "MMA", "league": "UFC"},
    "soccer/epl": {"sport": "Soccer", "league": "EPL"},
    "soccer/uefa": {"sport": "Soccer", "league": "UEFA"},
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
    elif "player" in desc_lower and ("points" in desc_lower or "rebounds" in desc_lower or "assists" in desc_lower):
        return MarketType.PLAYER_PROP
    elif "prop" in desc_lower or "milestones" in desc_lower:
        return MarketType.PLAYER_PROP
    elif "future" in desc_lower or "winner" in desc_lower or "outright" in desc_lower:
        return MarketType.FUTURES
    return MarketType.OTHER


def _parse_event(raw_event: dict, sport: str, league: str) -> Event:
    """Parse a single Bovada event into our Event model.
    
    This function captures ALL available markets, not just main markets.
    """
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
    
    # Process ALL display groups (categories of markets)
    for display_group in raw_event.get("displayGroups", []):
        group_desc = display_group.get("description", "")
        
        # Process ALL markets in each display group
        for raw_market in display_group.get("markets", []):
            market_key = raw_market.get("key", "")
            market_desc = raw_market.get("description", "")
            
            # Build full market name including the category for better context
            full_market_name = f"{group_desc} - {market_desc}" if group_desc else market_desc
            
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
                    name=full_market_name,
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


async def fetch_league(sport_league_slug: str, client: Optional[httpx.AsyncClient] = None, pre_match_only: bool = True) -> List[SportsbookSnapshot]:
    """Fetch all events for a specific Bovada sport/league.
    
    Args:
        sport_league_slug: e.g., 'basketball/nba', 'football/nfl'
        client: httpx async client
        pre_match_only: if True, only get pre-match events (not live)
    """
    close_client = False
    if client is None:
        client = httpx.AsyncClient(headers=HEADERS, timeout=30.0)
        close_client = True

    snapshots = []
    try:
        # Construct URL with working endpoint pattern
        url = f"{BASE_URL}/{sport_league_slug}"
        params = {
            "preMatchOnly": str(pre_match_only).lower(),
            "lang": "en"
        }
        
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        
        # Get sport/league info
        sport_info = SPORT_LEAGUE_MAP.get(sport_league_slug, {
            "sport": sport_league_slug.split("/")[0].title(),
            "league": sport_league_slug.split("/")[-1].upper()
        })
        sport_name = sport_info["sport"]
        league_name = sport_info["league"]
        now = datetime.now(timezone.utc)

        events = []
        # data is an array of groups, each with path and events
        for group in data:
            raw_events = group.get("events", [])
            for raw_event in raw_events:
                try:
                    event = _parse_event(raw_event, sport_name, league_name)
                    if event.markets:  # Only include events with odds
                        events.append(event)
                except Exception as e:
                    print(f"[Bovada] Error parsing event: {e}")
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
        print(f"[Bovada] Error fetching {sport_league_slug}: {e}")
    finally:
        if close_client:
            await client.aclose()

    return snapshots


# Backward compatibility alias
async def fetch_sport(sport_league_slug: str, client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    """Backward compatibility function - maps to fetch_league."""
    return await fetch_league(sport_league_slug, client)


async def fetch_all() -> List[SportsbookSnapshot]:
    """Fetch odds for all supported sports/leagues from Bovada."""
    all_snapshots = []
    async with httpx.AsyncClient(headers=HEADERS, timeout=30.0) as client:
        # Fetch each sport/league combination
        for slug in SPORT_LEAGUE_MAP.keys():
            print(f"[Bovada] Fetching {slug}...")
            snapshots = await fetch_league(slug, client)
            all_snapshots.extend(snapshots)
            print(f"[Bovada] Found {len(snapshots)} snapshots for {slug}")
    
    return all_snapshots


async def fetch_nfl(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_league("football/nfl", client)


async def fetch_nba(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_league("basketball/nba", client)


async def fetch_mlb(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_league("baseball/mlb", client)


async def fetch_nhl(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_league("hockey/nhl", client)


async def fetch_ufc(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_league("mma/ufc", client)