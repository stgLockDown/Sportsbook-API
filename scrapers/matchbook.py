"""
Matchbook Betting Exchange Scraper
==================================
Matchbook is a betting exchange offering back/lay prices.
Has 347+ events across multiple sports with competitive odds.
"""
import httpx
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, List
from scrapers.models import Event, Market, Outcome, MarketType, SportsbookSnapshot

logger = logging.getLogger(__name__)

BASE_URL = "https://api.matchbook.com/edge/rest"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# Matchbook sport IDs (discovered from API meta-tags)
SPORT_IDS = {
    "basketball": 4,
    "baseball": 3,
    "soccer": 15,
    "tennis": 9,
    "golf": 8,
    "cricket": 110,
    "rugby": 18,
    "rugby_league": 114,
    "darts": 116,
    "aussie_rules": 112,
    # These sports don't have confirmed IDs on Matchbook yet:
    # "football": ??,  # American football - not found
    # "hockey": ??,    # Ice hockey - not found
    # "boxing": ??,
    # "mma": ??,
}


def _decimal_to_american(decimal_odds: float) -> int:
    """Convert decimal odds to American odds."""
    if decimal_odds >= 2.0:
        return int(round((decimal_odds - 1) * 100))
    elif decimal_odds > 1.0:
        return int(round(-100 / (decimal_odds - 1)))
    return 0


async def fetch_sport(sport: str) -> List[SportsbookSnapshot]:
    """Fetch events for a sport from Matchbook."""
    sport_id = SPORT_IDS.get(sport)
    if not sport_id:
        logger.warning(f"Matchbook: No sport ID for '{sport}'")
        return []

    events = []
    try:
        async with httpx.AsyncClient(timeout=30, headers=HEADERS) as client:
            url = f"{BASE_URL}/events"
            params = {
                "sport-ids": sport_id,
                "status": "open",
                "per-page": 100,  # Increased from 50 to get more events
                "offset": 0,
                "include-prices": "true",
                "price-depth": 1,
                "price-mode": "expanded",
            }

            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                logger.warning(f"Matchbook {sport}: HTTP {resp.status_code}")
                return []

            data = resp.json()
            raw_events = data.get("events", [])

            for ev_data in raw_events:
                try:
                    event_id = str(ev_data.get("id", ""))
                    name = ev_data.get("name", "")
                    start_str = ev_data.get("start", "")
                    in_running = ev_data.get("in-running-flag", False)

                    # Parse teams from name
                    home_team = ""
                    away_team = ""

                    for sep in [" vs ", " v ", " @ ", " at ", " - "]:
                        if sep in name:
                            parts = name.split(sep, 1)
                            if sep in (" @ ", " at "):
                                # "Away @ Home" or "Away at Home" format
                                away_team = parts[0].strip()
                                home_team = parts[1].strip()
                            else:
                                # "Home vs Away" or "Home - Away" format
                                home_team = parts[0].strip()
                                away_team = parts[1].strip()
                            break

                    if not home_team and not away_team:
                        continue

                    start_time = None
                    if start_str:
                        try:
                            start_time = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                        except (ValueError, TypeError):
                            pass

                    # Parse markets
                    markets_data = ev_data.get("markets", [])
                    parsed_markets = []

                    for mkt in markets_data:
                        market_name = mkt.get("name", "")
                        market_type_raw = mkt.get("market-type", "")
                        runners = mkt.get("runners", [])

                        # Classify market - COMPREHENSIVE MODE
                        market_type = None
                        name_lower = market_name.lower()
                        
                        # DEBUG: Log half markets
                        if 'half' in name_lower:
                            logger.debug(f"Matchbook half market: {market_name} -> {name_lower}")
                        
                        # PRIORITIZE Half/Quarter Specific Markets first
                        if '1st half' in name_lower or 'first half' in name_lower:
                            if 'handicap' in name_lower or 'spread' in name_lower:
                                market_type = MarketType.SPREAD
                            elif 'total' in name_lower:
                                market_type = MarketType.TOTAL
                            else:
                                market_type = MarketType.GAME_PROP
                        elif '2nd half' in name_lower or 'second half' in name_lower:
                            if 'handicap' in name_lower or 'spread' in name_lower:
                                market_type = MarketType.SPREAD
                            elif 'total' in name_lower:
                                market_type = MarketType.TOTAL
                            else:
                                market_type = MarketType.GAME_PROP
                        elif 'quarter' in name_lower:
                            if 'handicap' in name_lower or 'spread' in name_lower:
                                market_type = MarketType.SPREAD
                            elif 'total' in name_lower:
                                market_type = MarketType.TOTAL
                            else:
                                market_type = MarketType.GAME_PROP
                        
                        if market_type is None:
                            # Player Props
                            player_keywords = [
                                'points', 'score', 'field goals', 'baskets',
                                'rebounds', 'boards', 'total rebounds',
                                'assists', 'helper',
                                'three pointers', '3-pointers', 'threes', '3s',
                                'blocks', 'steals', 'turnovers',
                                'double double', 'triple double',
                                'player', 'individual'
                            ]
                            for keyword in player_keywords:
                                if keyword in name_lower:
                                    market_type = MarketType.PLAYER_PROP
                                    break
                        
                        if market_type is None:
                            # Team Props
                            team_keywords = [
                                'team total', 'team over', 'team under',
                                'highest scoring', 'team to score',
                                'team points', 'winning margin'
                            ]
                            for keyword in team_keywords:
                                if keyword in name_lower:
                                    market_type = MarketType.TEAM_PROP
                                    break
                        
                        if market_type is None:
                            # Other Game Props
                            game_keywords = [
                                'both teams to score', 'odd/even',
                                'first to score', 'last to score',
                                'will there be overtime',
                                'race to', 'correct score', 'draw no bet'
                            ]
                            for keyword in game_keywords:
                                if keyword in name_lower:
                                    market_type = MarketType.GAME_PROP
                                    break
                        
                        if market_type is None:
                            # Core markets (last, as fallback)
                            if "moneyline" in name_lower or "match odds" in name_lower:
                                market_type = MarketType.MONEYLINE
                            elif name_lower == "winner" or market_type_raw == "outright":
                                market_type = MarketType.FUTURES
                            elif market_type_raw == "handicap" or "handicap" in name_lower or "spread" in name_lower:
                                market_type = MarketType.SPREAD
                            elif market_type_raw == "total" or "total" in name_lower or "over" in name_lower:
                                market_type = MarketType.TOTAL
                            elif market_type_raw in ("one_x_two", "win-draw-win"):
                                market_type = MarketType.MONEYLINE
                            else:
                                # Default to GAME_PROP for anything else
                                market_type = MarketType.GAME_PROP

                        if market_type is None:
                            continue

                        outcomes = []
                        for runner in runners:
                            runner_name = runner.get("name", "")
                            prices = runner.get("prices", [])
                            handicap = runner.get("handicap")

                            # Get best back price (Matchbook uses "win" for back in binary markets)
                            best_back = None
                            for price in prices:
                                side = price.get("side", "")
                                # Matchbook uses "win" for back, "lose" for lay in binary exchange markets
                                if side == "win" or side == "back":
                                    decimal_odds = price.get("decimal-odds", 0)
                                    if decimal_odds and decimal_odds > 1.0:
                                        if best_back is None or decimal_odds > best_back:
                                            best_back = decimal_odds

                            if best_back and best_back > 1.0:
                                american_odds = _decimal_to_american(best_back)
                                point = float(handicap) if handicap else None

                                outcomes.append(Outcome(
                                    name=runner_name,
                                    price_american=american_odds,
                                    price_decimal=round(best_back, 3),
                                    point=point,
                                    description="Exchange back price",
                                ))

                        if outcomes:
                            parsed_markets.append(Market(
                                market_type=market_type,
                                name=market_name,
                                outcomes=outcomes,
                            ))

                    if not parsed_markets:
                        continue

                    # Determine league
                    league = ""
                    meta_tags = ev_data.get("meta-tags", [])
                    if meta_tags:
                        for tag in meta_tags:
                            if tag.get("type") == "COMPETITION":
                                league = tag.get("name", "")
                                break
                    if not league:
                        category = ev_data.get("category", {})
                        league = category.get("name", sport.upper())

                    events.append(Event(
                        event_id=event_id,
                        sport=sport,
                        league=league,
                        home_team=home_team,
                        away_team=away_team,
                        description=f"{away_team} @ {home_team}",
                        start_time=start_time,
                        is_live=in_running,
                        markets=parsed_markets,
                    ))

                except Exception as e:
                    logger.debug(f"Matchbook event parse error: {e}")
                    continue

    except Exception as e:
        logger.error(f"Matchbook error for {sport}: {e}")

    logger.info(f"Matchbook: {len(events)} {sport} events")

    if not events:
        return []

    return [SportsbookSnapshot(
        sportsbook="Matchbook",
        sport=sport,
        league=sport,
        fetched_at=datetime.now(timezone.utc),
        events=events,
    )]