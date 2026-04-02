"""
DraftKings direct scraper - Comprehensive Market Coverage Upgrade
Uses the DK sportsbook content API to get sports navigation and events.
Enhanced to capture ALL available markets including:
- Moneylines, spreads, totals
- Player props (all types)
- Team props
- Game props
- Alternate lines
- Futures and special markets
"""
import httpx
import random
from datetime import datetime, timezone
from typing import List, Optional
from .models import SportsbookSnapshot, Event, Market, Outcome, MarketType

BASE_URL = "https://sportsbook-nash.draftkings.com"

# Multiple user agents to rotate through
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
]

def get_headers() -> dict:
    """Generate headers with a random user agent"""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://sportsbook.draftkings.com",
        "Origin": "https://sportsbook.draftkings.com",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

# DraftKings event group IDs for major sports
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
SITE_CODES = ["US-NJ-SB", "US-VA-SB", "US-PA-SB", "US-CO-SB", "US-IL-SB", "US-AZ-SB",
              "US-IN-SB", "US-IA-SB", "US-WY-SB", "US-MI-SB"]
DK_CONTENT_CODES = ["dkusnj", "dkusva", "dkuspa", "dkusco", "dkusil", "dkusaz",
                     "dkusin", "dkusia", "dkuswy", "dkusmi"]

def _classify_market(name: str, category: str = "", subcategory: str = "") -> MarketType:
    """
    Enhanced market classification with comprehensive category detection.
    Now detects player props, team props, game props, and alternate lines.
    """
    name_lower = name.lower()
    cat_lower = category.lower()
    sub_lower = subcategory.lower()
    
    # Combine all text for classification
    combined_text = f"{name_lower} {cat_lower} {sub_lower}"
    
    # PLAYER PROPS - Check for player-specific keywords
    player_keywords = [
        'player', 'points', 'rebounds', 'assists', 'threes', 'three pointers',
        'made threes', 'three point', '3-point', '3 point',
        'blocks', 'steals', 'turnovers', 'double double', 'triple double',
        'points + rebounds', 'points + assists', 'rebounds + assists',
        'p+r', 'p+a', 'r+a', 'points/rebounds/assists', 'points, rebounds, assists',
        'field goals', 'fg made', 'free throws', 'ft made',
        'points + rebounds + assists', 'total bases', 'hits',
        'passing yards', 'passing touchdowns', 'rushing yards', 'rushing touchdowns',
        'receiving yards', 'receiving touchdowns', 'completions',
        'interceptions', 'sacks', 'tackles', 'tackles + assists',
        'first downs', 'touchdowns scored', 'fumble recovery touchdown',
        'safeties', 'two point conversions',
        'kicking points', 'field goals made', 'extra points made',
        'win', 'strikeouts', 'hits allowed', 'runs allowed', 'innings pitched',
        'complete game', 'shutout', 'save',
        'goals', 'shots on goal', 'assists', 'points', 'saves',
        'first period goal', 'anytime goal scorer', 'last goal scorer',
        'ace', 'double faults', 'games won', 'sets won',
        'fights won by', 'method of victory', 'round betting',
        'scoreboard', 'scorecast', 'wincast',
    ]
    
    if any(keyword in combined_text for keyword in player_keywords):
        return MarketType.PLAYER_PROP
    
    # TEAM PROPS - Team-specific performance
    team_keywords = [
        'team total', 'team points', 'first half team', 'second half team',
        'team to score', 'team to score first', 'team to score last',
        'team to score most', 'home team', 'away team', 'visiting team',
        'quarter', 'period', 'inning', 'half', 'team',
        'race to', 'margin of victory', 'exact score',
        'will there be', 'highest scoring quarter', 'highest scoring half',
        'team with most', 'team leads at',
    ]
    
    if any(keyword in combined_text for keyword in team_keywords):
        return MarketType.TEAM_PROP
    
    # GAME PROPS - Game-specific events
    game_keywords = [
        'alternatives', 'alternate', 'exact', 'score', 'outcome',
        'result', 'will the game go to overtime', 'overtime',
        'both teams score', 'btts', 'draw no bet', 'double chance',
        'winning margin', 'total points', 'total goals', 'total runs',
        'total score', 'first to', 'last to', 'anytime',
        'match', 'game props', 'special', 'novelty',
    ]
    
    if any(keyword in combined_text for keyword in game_keywords):
        return MarketType.GAME_PROP
    
    # CORE MARKETS
    if "moneyline" in name_lower or "money line" in name_lower or "winner" in name_lower:
        return MarketType.MONEYLINE
    elif "spread" in name_lower or "handicap" in name_lower:
        return MarketType.SPREAD
    elif "total" in name_lower or "over/under" in name_lower or "over under" in name_lower:
        return MarketType.TOTAL
    elif "future" in name_lower or "outright" in name_lower or "champion" in name_lower:
        return MarketType.FUTURES
    
    # FUTURE/PROP indicators
    if "prop" in name_lower or "special" in cat_lower or "novelty" in cat_lower:
        return MarketType.OTHER
    
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
    """Try to fetch event group data from multiple DK site codes with retries."""
    # Randomize the order of site codes to distribute load
    site_codes_shuffled = SITE_CODES.copy()
    random.shuffle(site_codes_shuffled)
    
    for site_code in site_codes_shuffled:
        url = f"{BASE_URL}/sites/{site_code}/api/v5/eventgroups/{group_id}?format=json"
        headers = get_headers()
        
        try:
            # Add small delay to avoid rate limiting
            await asyncio.sleep(random.uniform(0.5, 1.5))
            r = await client.get(url, headers=headers, timeout=20)
            
            if r.status_code == 200:
                data = r.json()
                if data and "eventGroup" in data:
                    return data
            elif r.status_code == 403:
                # Try next site code on 403
                continue
        except Exception as e:
            # Continue to next site code on error
            continue
    
    return None


async def _try_fetch_categories(client: httpx.AsyncClient, group_id: int) -> Optional[dict]:
    """Try to fetch categories/subcategories for an event group with retries."""
    content_codes_shuffled = DK_CONTENT_CODES.copy()
    random.shuffle(content_codes_shuffled)
    
    for content_code in content_codes_shuffled:
        url = f"{BASE_URL}/api/sportscontent/{content_code}/v1/leagues/{group_id}/categories/487?format=json"
        headers = get_headers()
        
        try:
            await asyncio.sleep(random.uniform(0.5, 1.5))
            r = await client.get(url, headers=headers, timeout=20)
            
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 403:
                continue
        except:
            continue
    
    return None


async def fetch_sport(sport: str) -> List[SportsbookSnapshot]:
    """
    Fetch odds for a sport from DraftKings.
    Captures ALL available markets including player props, team props, game props.
    """
    group_id = SPORT_EVENT_GROUPS.get(sport)
    if not group_id:
        return []

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        # Try eventgroup endpoint first
        data = await _try_fetch_eventgroup(client, group_id)
        
        if not data:
            # Try categories endpoint as fallback
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
    
    # Parse ALL offers - no filtering
    for category in offer_categories:
        cat_name = category.get("name", "")
        
        # Handle both old and new API structures
        sub_categories = category.get("offerSubcategoryDescriptors", [])
        if not sub_categories:
            sub_categories = category.get("offerSubcategories", [])
        
        # Also process direct offers in category
        direct_offers = category.get("offers", [])
        
        for sub_cat in sub_categories:
            sub_name = sub_cat.get("name", "")
            
            # Handle different API response structures
            if "offerSubcategory" in sub_cat:
                offers = sub_cat["offerSubcategory"].get("offers", [])
            else:
                offers = sub_cat.get("offers", [])
            
            # Process all offers
            for offer_group in offers:
                if not isinstance(offer_group, list):
                    offer_group = [offer_group]
                
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
                    
                    # Parse market with enhanced classification
                    market_name = offer.get("label", sub_name)
                    market_type = _classify_market(market_name, cat_name, sub_name)
                    
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


# Import asyncio for sleep functionality
import asyncio