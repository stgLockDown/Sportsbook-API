"""
Ladbrokes AU scraper — Entain platform.
Returns events with full odds (fractional → decimal → American).
Covers 1800+ events across all sports.
"""
import httpx
from datetime import datetime, timezone
from typing import List, Optional
from .models import SportsbookSnapshot, Event, Market, Outcome, MarketType

BASE_URL = "https://api.ladbrokes.com.au/v2/sport"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Referer": "https://www.ladbrokes.com.au",
    "Origin": "https://www.ladbrokes.com.au",
}

# Competition name patterns → sport key mapping
SPORT_FILTERS = {
    "nba": ["NBA"],
    "ncaab": ["NCAA Men", "NCAA Women", "NCAAB"],
    "nfl": ["NFL"],
    "mlb": ["MLB", "World Baseball Classic"],
    "nhl": ["NHL"],
    "soccer": ["Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1",
               "Champions League", "Europa League", "MLS", "A-League",
               "World Cup", "Copa America", "Euro 202", "Liga MX",
               "Eredivisie", "Primeira Liga", "Scottish Premiership",
               "Championship", "League One", "League Two",
               "Super Lig", "Superliga", "Allsvenskan"],
    "tennis": ["ATP", "WTA", "ITF", "Grand Slam", "Australian Open",
               "French Open", "Wimbledon", "US Open", "Indian Wells",
               "Miami Open", "Roland Garros"],
    "mma": ["UFC", "MMA", "Bellator", "PFL"],
    "boxing": ["Boxing"],
    "golf": ["PGA", "LPGA", "European Tour", "DP World", "Masters",
             "Open Championship", "Arnold Palmer", "Players Championship"],
    "cricket": ["Cricket", "IPL", "Big Bash", "Test Match", "ODI", "T20"],
    "rugby_league": ["NRL", "Super League", "Rugby League"],
    "rugby_union": ["Rugby Union", "Super Rugby", "Six Nations", "Rugby Championship"],
    "afl": ["AFL"],
    "darts": ["Darts", "PDC", "BDO"],
    "table_tennis": ["Table Tennis"],
    "handball": ["Handball"],
    "volleyball": ["Volleyball"],
    "baseball": ["MLB", "KBO", "NPB", "World Baseball"],
    "ice_hockey": ["NHL", "AHL", "KHL", "SHL", "Liiga"],
    "esports": ["Esports", "CS:", "Dota", "League of Legends", "Valorant"],
    "snooker": ["Snooker"],
    "cycling": ["Cycling", "Tour de"],
    "motorsport": ["Formula 1", "F1", "NASCAR", "MotoGP", "IndyCar", "V8"],
}


def _fractional_to_decimal(numerator: int, denominator: int) -> float:
    """Convert fractional odds to decimal."""
    if denominator == 0:
        return 0.0
    return round(numerator / denominator + 1, 4)


def _decimal_to_american(decimal_odds: float) -> Optional[int]:
    """Convert decimal odds to American."""
    if decimal_odds <= 1.0:
        return None
    if decimal_odds >= 2.0:
        return int(round((decimal_odds - 1) * 100))
    else:
        return int(round(-100 / (decimal_odds - 1)))


def _classify_market(market_name: str) -> MarketType:
    """Classify market type from market name."""
    name_lower = market_name.lower()
    if name_lower in ("head to head", "match result", "moneyline", "money line",
                       "match winner", "to win", "match betting"):
        return MarketType.MONEYLINE
    elif "spread" in name_lower or "handicap" in name_lower or "line" in name_lower:
        return MarketType.SPREAD
    elif "total" in name_lower or "over/under" in name_lower or "over under" in name_lower:
        return MarketType.TOTAL
    elif "player" in name_lower or "scorer" in name_lower or "points" in name_lower:
        return MarketType.PLAYER_PROP
    elif "winner" in name_lower and ("season" in name_lower or "premiership" in name_lower or "championship" in name_lower):
        return MarketType.FUTURES
    else:
        return MarketType.OTHER


def _match_sport(competition_name: str, sport_key: str) -> bool:
    """Check if a competition matches the requested sport."""
    if sport_key not in SPORT_FILTERS:
        return True  # No filter, return all
    patterns = SPORT_FILTERS[sport_key]
    comp_lower = competition_name.lower()
    for pattern in patterns:
        if pattern.lower() in comp_lower:
            return True
    return False


async def fetch_sport(sport: str) -> List[SportsbookSnapshot]:
    """Fetch odds for a sport from Ladbrokes AU."""
    snapshots = []
    
    async with httpx.AsyncClient(timeout=25) as client:
        try:
            r = await client.get(
                f"{BASE_URL}/event-request?category_id=6",
                headers=HEADERS,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"[Ladbrokes AU] Error fetching data: {e}")
            return []
    
    raw_events = data.get("events", {})
    raw_markets = data.get("markets", {})
    raw_prices = data.get("prices", {})
    raw_entrants = data.get("entrants", {})
    
    # Build entrant → price lookup
    # Price keys are "entrant_id:source_id"
    entrant_prices = {}
    for price_key, price_val in raw_prices.items():
        ent_id = price_key.split(":")[0]
        if ent_id not in entrant_prices:
            entrant_prices[ent_id] = price_val
    
    # Build event → markets lookup
    event_markets = {}
    for mid, mkt in raw_markets.items():
        eid = mkt.get("event_id")
        if eid:
            if eid not in event_markets:
                event_markets[eid] = []
            event_markets[eid].append(mkt)
    
    events = []
    for eid, ev in raw_events.items():
        comp = ev.get("competition", {})
        comp_name = comp.get("name", "")
        
        # Filter by sport
        if not _match_sport(comp_name, sport):
            continue
        
        # Parse event name (usually "Team A vs Team B")
        name = ev.get("name", "")
        parts = name.split(" vs ")
        if len(parts) == 2:
            home_team = parts[0].strip()
            away_team = parts[1].strip()
        elif " @ " in name:
            parts = name.split(" @ ")
            away_team = parts[0].strip()
            home_team = parts[1].strip()
        else:
            home_team = name
            away_team = ""
        
        # Parse start time
        start_str = ev.get("advertised_start", "")
        start_time = None
        if start_str:
            try:
                start_time = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            except:
                pass
        
        is_live = ev.get("match_status", "") in ("InProgress", "Live")
        
        # Build markets
        markets = []
        ev_mkts = event_markets.get(eid, [])
        
        for mkt in ev_mkts:
            market_name = mkt.get("name", "")
            market_type = _classify_market(market_name)
            
            outcomes = []
            ent_ids = mkt.get("entrant_ids", [])
            
            for ent_id in ent_ids:
                ent = raw_entrants.get(ent_id, {})
                ent_name = ent.get("name", "Unknown")
                
                # Get price
                price_data = entrant_prices.get(ent_id, {})
                odds = price_data.get("odds", {})
                num = odds.get("numerator", 0)
                den = odds.get("denominator", 1)
                
                if den == 0:
                    continue
                
                decimal_odds = _fractional_to_decimal(num, den)
                american_odds = _decimal_to_american(decimal_odds)
                
                # Extract point/handicap if present
                point = None
                handicap = ent.get("handicap")
                if handicap is not None:
                    try:
                        point = float(handicap)
                    except:
                        pass
                
                outcomes.append(Outcome(
                    name=ent_name,
                    price_american=american_odds,
                    price_decimal=decimal_odds,
                    point=point,
                ))
            
            if outcomes:
                markets.append(Market(
                    market_type=market_type,
                    name=market_name,
                    outcomes=outcomes,
                ))
        
        if markets:
            events.append(Event(
                event_id=eid,
                sport=sport,
                league=comp_name,
                home_team=home_team,
                away_team=away_team,
                description=name,
                start_time=start_time,
                is_live=is_live,
                markets=markets,
            ))
    
    if events:
        snapshots.append(SportsbookSnapshot(
            sportsbook="Ladbrokes AU",
            sport=sport,
            league=sport.upper(),
            events=events,
            fetched_at=datetime.now(timezone.utc),
        ))
    
    return snapshots