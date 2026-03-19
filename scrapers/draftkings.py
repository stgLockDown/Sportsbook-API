"""
DraftKings direct scraper.
Uses the DK sportsbook content API to get sports navigation and events.
The nav/sports endpoint returns sport groups; we then try to get event data
via the eventgroups API.
"""
import httpx
from datetime import datetime, timezone
from typing import List, Optional
from .models import SportsbookSnapshot, Event, Market, Outcome, MarketType

BASE_URL = "https://sportsbook-nash.draftkings.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://sportsbook.draftkings.com",
    "Origin": "https://sportsbook.draftkings.com",
}

# DraftKings event group IDs for major sports
# These are the league-level IDs used in the DK API
SPORT_EVENT_GROUPS = {
    "nba": 42648,
    "nfl": 88808,
    "mlb": 84240,
    "nhl": 42133,
    "ncaab": 92483,
    "ncaaf": 87637,
    "soccer": 40253,
    "tennis": 92000,
    "mma": 9034,
    "golf": 13,
    "boxing": 9035,
}

# DraftKings uses state-specific site codes
SITE_CODES = ["US-NJ-SB", "US-VA-SB", "US-PA-SB", "US-CO-SB", "US-IL-SB", "US-AZ-SB"]
DK_CONTENT_CODES = ["dkusnj", "dkusva", "dkuspa", "dkusco", "dkusil", "dkusaz"]


def _classify_market(name: str) -> MarketType:
    name_lower = name.lower()
    if "moneyline" in name_lower or "money line" in name_lower or "winner" in name_lower:
        return MarketType.MONEYLINE
    elif "spread" in name_lower or "handicap" in name_lower:
        return MarketType.SPREAD
    elif "total" in name_lower or "over/under" in name_lower:
        return MarketType.TOTAL
    elif "player" in name_lower or "prop" in name_lower:
        return MarketType.PLAYER_PROP
    elif "future" in name_lower or "outright" in name_lower:
        return MarketType.FUTURES
    return MarketType.OTHER


def _parse_american_odds(odds_val) -> Optional[int]:
    """Parse American odds from DK format."""
    if odds_val is None:
        return None
    try:
        return int(odds_val)
    except (ValueError, TypeError):
        return None


def _american_to_decimal(american: int) -> float:
    """Convert American odds to decimal."""
    if american > 0:
        return round(american / 100 + 1, 4)
    elif american < 0:
        return round(100 / abs(american) + 1, 4)
    return 0.0


async def _try_fetch_eventgroup(client: httpx.AsyncClient, group_id: int) -> Optional[dict]:
    """Try to fetch event group data from multiple DK site codes."""
    for site_code in SITE_CODES:
        url = f"{BASE_URL}/sites/{site_code}/api/v5/eventgroups/{group_id}?format=json"
        try:
            r = await client.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                data = r.json()
                if data and "eventGroup" in data:
                    return data
        except:
            continue
    return None


async def _try_fetch_categories(client: httpx.AsyncClient, group_id: int) -> Optional[dict]:
    """Try to fetch categories/subcategories for an event group."""
    for content_code in DK_CONTENT_CODES:
        url = f"{BASE_URL}/api/sportscontent/{content_code}/v1/leagues/{group_id}/categories/487?format=json"
        try:
            r = await client.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                return r.json()
        except:
            continue
    return None


async def fetch_sport(sport: str) -> List[SportsbookSnapshot]:
    """Fetch odds for a sport from DraftKings."""
    group_id = SPORT_EVENT_GROUPS.get(sport)
    if not group_id:
        return []

    async with httpx.AsyncClient(timeout=20) as client:
        # Try eventgroup endpoint
        data = await _try_fetch_eventgroup(client, group_id)
        
        if not data:
            # Try categories endpoint
            data = await _try_fetch_categories(client, group_id)
        
        if not data:
            return []

    events = []
    
    # Parse eventGroup format
    event_group = data.get("eventGroup", {})
    offer_categories = event_group.get("offerCategories", data.get("offerCategories", []))
    raw_events = event_group.get("events", data.get("events", []))
    
    # Build event lookup
    event_lookup = {}
    if isinstance(raw_events, list):
        for ev in raw_events:
            event_lookup[ev.get("eventId")] = ev
    
    # Parse offers
    for category in offer_categories:
        cat_name = category.get("name", "")
        sub_categories = category.get("offerSubcategoryDescriptors", [])
        
        for sub_cat in sub_categories:
            sub_name = sub_cat.get("name", "")
            offers = sub_cat.get("offerSubcategory", {}).get("offers", [])
            
            for offer_group in offers:
                if not isinstance(offer_group, list):
                    continue
                
                for offer in offer_group:
                    event_id = str(offer.get("eventId", ""))
                    ev_data = event_lookup.get(offer.get("eventId"), {})
                    
                    if not ev_data:
                        continue
                    
                    # Parse event info
                    home_team = ev_data.get("teamName1", "")
                    away_team = ev_data.get("teamName2", "")
                    description = f"{away_team} @ {home_team}" if away_team else home_team
                    
                    start_str = ev_data.get("startDate", "")
                    start_time = None
                    if start_str:
                        try:
                            start_time = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                        except:
                            pass
                    
                    # Parse market
                    market_name = offer.get("label", sub_name)
                    market_type = _classify_market(market_name)
                    
                    outcomes = []
                    for outcome_data in offer.get("outcomes", []):
                        o_name = outcome_data.get("label", "")
                        o_odds = outcome_data.get("oddsAmerican")
                        american = _parse_american_odds(o_odds)
                        decimal_odds = _american_to_decimal(american) if american else None
                        
                        point = None
                        line = outcome_data.get("line")
                        if line is not None:
                            try:
                                point = float(line)
                            except:
                                pass
                        
                        if american is not None:
                            outcomes.append(Outcome(
                                name=o_name,
                                price_american=american,
                                price_decimal=decimal_odds,
                                point=point,
                            ))
                    
                    if outcomes:
                        # Check if we already have this event
                        existing = None
                        for e in events:
                            if e.event_id == event_id:
                                existing = e
                                break
                        
                        market = Market(
                            market_type=market_type,
                            name=market_name,
                            outcomes=outcomes,
                        )
                        
                        if existing:
                            existing.markets.append(market)
                        else:
                            events.append(Event(
                                event_id=event_id,
                                sport=sport,
                                league=event_group.get("name", sport.upper()),
                                home_team=home_team,
                                away_team=away_team,
                                description=description,
                                start_time=start_time,
                                is_live=ev_data.get("eventStatus", {}).get("state", "") == "STARTED",
                                markets=[market],
                            ))

    snapshots = []
    if events:
        snapshots.append(SportsbookSnapshot(
            sportsbook="DraftKings",
            sport=sport,
            league=sport.upper(),
            events=events,
            fetched_at=datetime.now(timezone.utc),
        ))

    return snapshots