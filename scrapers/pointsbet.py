"""
PointsBet Scraper — US sportsbook with deep market coverage.
Enhanced to capture ALL available markets including player props, team props, alternate lines.

Uses two-step approach:
1. Get event list from competitions/{id}/events/featured
2. Get full markets from events/{key} detail endpoint

Each event detail returns 90+ markets including ML, spread, total, and props.
"""

import httpx
import asyncio
from datetime import datetime, timezone
from typing import List, Optional
from scrapers.models import Event, Market, Outcome, SportsbookSnapshot, MarketType

# ─── Competition IDs ───────────────────────────────────────
COMPETITION_IDS = {
    "basketball_nba": 7176,
    "basketball_ncaab": 7178,
    "basketball_wnba": 7593,
    "ice_hockey_nhl": 7596,
    "baseball_mlb": 7592,
    "american_football_nfl": 7589,
    "american_football_ncaaf": 7590,
    "soccer_epl": 7412,
    "soccer_mls": 7591,
    "mma": 7602,
    "tennis_atp": 7413,
    "golf": 7594,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Accept": "application/json",
}

BASE_URL = "https://api.pointsbet.com/api/v2"


def _decimal_to_american(decimal_odds: float) -> Optional[int]:
    """Convert decimal odds to American."""
    if decimal_odds is None or decimal_odds <= 1:
        return None
    if decimal_odds >= 2.0:
        return int(round((decimal_odds - 1) * 100))
    else:
        return int(round(-100 / (decimal_odds - 1)))


def _classify_market(market_name: str) -> MarketType:
    """
    Enhanced market classification for PointsBet.
    Detects player props, team props, game props, alternate lines.
    """
    name_lower = market_name.lower()
    
    # PLAYER PROPS - Player-specific betting markets
    player_prop_keywords = [
        # Basketball props
        'points', 'rebounds', 'assists', 'threes', 'made threes',
        'three pointers', 'three point', '3-point', '3 point', 'blocks', 'steals',
        'turnovers', 'double double', 'triple double', 'points + rebounds',
        'points + assists', 'rebounds + assists', 'p+r', 'p+a', 'r+a',
        # Football props
        'passing yards', 'passing touchdowns', 'rushing yards', 'rushing touchdowns',
        'receiving yards', 'receiving touchdowns', 'completions', 'interceptions',
        'sacks', 'tackles', 'tackles + assists', 'first downs', 'touchdowns scored',
        # Baseball props
        'total bases', 'hits', 'home runs', 'runs batted in', 'strikeouts',
        'hits allowed', 'runs allowed', 'innings pitched', 'strikeouts thrown',
        # Hockey props
        'goals', 'shots on goal', 'saves', 'first period goal', 'anytime goal',
        'last goal', 'goals scored',
        # Tennis props
        'aces', 'double faults', 'games won', 'sets won', 'break points',
        # General player indicators
        'player', 'pts', 'reb', 'ast', 'performance', 'to make', 'to be', 'to have',
    ]
    
    if any(keyword in name_lower for keyword in player_prop_keywords):
        return MarketType.PLAYER_PROP
    
    # TEAM PROPS - Team-specific performance markets
    team_prop_keywords = [
        'team to score', 'team to score first', 'team to score last',
        'team to score most', 'team total', 'team points',
        'first basket', 'first field goal', 'first touchdown',
        'highest scoring quarter', 'highest scoring half',
        'team with most', 'team leads at', 'race to',
        'winning margin', 'exact score',
        'quarter', 'period', 'inning', 'half',
    ]
    
    if any(keyword in name_lower for keyword in team_prop_keywords):
        return MarketType.PLAYER_PROP  # Map to PLAYER_PROP for now
    
    # GAME PROPS - Game-specific markets
    game_prop_keywords = [
        'alternatives', 'alternate', 'both teams score', 'btts',
        'draw no bet', 'double chance', 'overtime', 'special', 'novelty',
    ]
    
    if any(keyword in name_lower for keyword in game_prop_keywords):
        return MarketType.OTHER  # Map to OTHER for now
    
    # CORE MARKETS
    if "moneyline" in name_lower or "money line" in name_lower or "match result" in name_lower:
        return MarketType.MONEYLINE
    elif "spread" in name_lower or "handicap" in name_lower:
        return MarketType.SPREAD
    elif "total" in name_lower:
        return MarketType.TOTAL
    elif "future" in name_lower or "outright" in name_lower or "outright" in name_lower:
        return MarketType.FUTURES
    
    return MarketType.OTHER


def _parse_markets_from_detail(detail: dict) -> List[Market]:
    """
    Parse ALL markets from PointsBet event detail response.
    Enhanced to capture player props, team props, alternate lines, etc.
    """
    markets: List[Market] = []
    fom = detail.get("fixedOddsMarkets", [])

    for m in fom:
        market_name = m.get("eventName", m.get("name", ""))
        outcomes_raw = m.get("outcomes", [])
        if not outcomes_raw:
            continue

        # Use enhanced market classification
        market_type = _classify_market(market_name)

        # REMOVED FILTERING: Now capture ALL market types, not just core
        # Old code was: if mtype not in (MarketType.MONEYLINE, MarketType.SPREAD, MarketType.TOTAL): continue

        # REMOVED ALTERNATE LINE FILTERING: Now capture alternate lines too
        # Old code was: if mtype in (MarketType.SPREAD, MarketType.TOTAL) and len(outcomes_raw) > 2: continue

        # Parse outcomes
        outcomes = []
        for o in outcomes_raw:
            price = o.get("price")
            if price is None:
                continue
            points = o.get("points")
            outcomes.append(Outcome(
                name=o.get("name", ""),
                price_decimal=float(price),
                price_american=_decimal_to_american(float(price)),
                point=float(points) if points is not None else None,
            ))

        if outcomes:
            markets.append(Market(
                market_type=market_type,
                name=market_name,
                outcomes=outcomes,
            ))

    return markets


async def fetch_sport(sport: str) -> List[SportsbookSnapshot]:
    """
    Fetch odds from PointsBet for a given sport.
    Captures ALL available markets including player props, team props, alternate lines.
    """
    comp_id = COMPETITION_IDS.get(sport)
    if comp_id is None:
        return []

    from ._proxy import get_client_kwargs
    async with httpx.AsyncClient(timeout=20, headers=HEADERS, **get_client_kwargs("US")) as client:
        # Step 1: Get event list
        try:
            url = f"{BASE_URL}/competitions/{comp_id}/events/featured?includeLive=true"
            resp = await client.get(url)
            if resp.status_code != 200:
                return []
            data = resp.json()
        except Exception:
            return []

        event_list = data.get("events", [])
        if not event_list:
            return []

        # Step 2: Fetch event details concurrently (limit to 10 for speed)
        event_keys = [ev.get("key") for ev in event_list[:10] if ev.get("key")]

        async def fetch_detail(key):
            try:
                r = await client.get(f"{BASE_URL}/events/{key}")
                if r.status_code == 200:
                    return key, r.json()
            except Exception:
                pass
            return key, None

        # Fetch all at once for speed
        details = {}
        results = await asyncio.gather(*[fetch_detail(k) for k in event_keys])
        for key, detail in results:
            if detail:
                details[key] = detail

    now = datetime.now(timezone.utc)
    events: List[Event] = []

    # Build event metadata from the list, markets from details
    event_meta = {ev.get("key"): ev for ev in event_list}

    for key, detail in details.items():
        meta = event_meta.get(key, {})
        
        home_team = meta.get("homeTeam", "")
        away_team = meta.get("awayTeam", "")
        event_name = meta.get("name", f"{away_team} @ {home_team}")

        # Parse start time
        starts_at = meta.get("startsAt", "")
        start_time = None
        if starts_at:
            try:
                start_time = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
            except Exception:
                pass

        # Check if live
        is_live = meta.get("liveEventCount", 0) > 0

        # Parse ALL markets now
        markets = _parse_markets_from_detail(detail)
        if not markets:
            continue

        events.append(Event(
            event_id=f"pb_{key}",
            sport=sport,
            league=meta.get("competitionName", sport.upper()),
            home_team=home_team,
            away_team=away_team,
            description=event_name,
            start_time=start_time,
            is_live=is_live,
            markets=markets,
        ))

    if not events:
        return []

    return [SportsbookSnapshot(
        sportsbook="pointsbet",
        sport=sport,
        league=sport.upper(),
        fetched_at=now,
        events=events,
    )]