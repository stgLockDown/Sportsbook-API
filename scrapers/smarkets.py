"""
Smarkets Betting Exchange Scraper
=================================
Smarkets is a betting exchange (like Betfair) where users bet against each other.
Provides back/lay prices which often represent true market odds.

Supports 14+ sports including basketball, football, hockey, baseball, soccer,
tennis, boxing, MMA, cricket, rugby, darts, table tennis, volleyball, handball.
"""
import httpx
from ._proxy import get_client_kwargs
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, List
from scrapers.models import Event, Market, Outcome, MarketType, SportsbookSnapshot

logger = logging.getLogger(__name__)

BASE_URL = "https://api.smarkets.com/v3"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# Smarkets event type mappings
SPORT_EVENT_TYPES = {
    "basketball": "basketball_match",
    "football": "american_football_match",
    "baseball": "baseball_match",
    "hockey": "ice_hockey_match",
    "soccer": "football_match",
    "tennis": "tennis_match",
    "boxing": "boxing_match",
    "mma": "mma_match",
    "cricket": "cricket_match",
    "rugby": "rugby_union_match",
    "rugby_league": "rugby_league_match",
    "darts": "darts_match",
    "table_tennis": "table_tennis_match",
    "volleyball": "volleyball_match",
    "handball": "handball_match",
}


def _decimal_to_american(decimal_odds: float) -> int:
    """Convert decimal odds to American odds."""
    if decimal_odds >= 2.0:
        return int(round((decimal_odds - 1) * 100))
    elif decimal_odds > 1.0:
        return int(round(-100 / (decimal_odds - 1)))
    return 0


def _percent_to_decimal(percent: float) -> float:
    """Convert Smarkets percentage to decimal odds."""
    if percent and percent > 0:
        return round(100.0 / percent, 3)
    return 0.0


async def fetch_sport(sport: str) -> List[SportsbookSnapshot]:
    """Fetch events for a sport from Smarkets."""
    event_type = SPORT_EVENT_TYPES.get(sport)
    if not event_type:
        logger.warning(f"Smarkets: No event type for '{sport}'")
        return []

    events = []
    try:
        async with httpx.AsyncClient(timeout=60, headers=HEADERS, **get_client_kwargs("UK")) as client:
            # Step 1: Get upcoming events
            params = {
                "type": event_type,
                "state": "upcoming",
                "limit": 50,
                "sort": "start_datetime,id",
            }

            resp = await client.get(f"{BASE_URL}/events/", params=params)
            if resp.status_code != 200:
                logger.warning(f"Smarkets {sport}: HTTP {resp.status_code}")
                return []

            data = resp.json()
            raw_events = data.get("events", [])

            if not raw_events:
                return []
            
            # Limit to first 5 events for testing with rate limiting
            raw_events = raw_events[:5]

            # Step 2: For each event, get markets and prices
            # Reduced to 1 to avoid rate limiting (API is very aggressive)
            sem = asyncio.Semaphore(1)

            async def process_event(ev_data):
                async with sem:
                    event_id = ev_data.get("id", "")
                    name = ev_data.get("name", "")
                    full_slug = ev_data.get("full_slug", "")
                    start_str = ev_data.get("start_datetime", "")
                    state = ev_data.get("state", "")

                    # Parse teams from name
                    home_team = ""
                    away_team = ""

                    for sep in [" vs ", " v ", " @ ", " - "]:
                        if sep in name:
                            parts = name.split(sep, 1)
                            if sep == " @ ":
                                away_team = parts[0].strip()
                                home_team = parts[1].strip()
                            else:
                                home_team = parts[0].strip()
                                away_team = parts[1].strip()
                            break

                    if not home_team and not away_team:
                        return None

                    start_time = None
                    if start_str:
                        try:
                            start_time = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                        except (ValueError, TypeError):
                            pass

                    is_live = state == "live"

                    # Get markets for this event - Increased limit for comprehensive coverage
                    try:
                        markets_resp = await client.get(
                            f"{BASE_URL}/events/{event_id}/markets/",
                            params={"limit": 50}  # Reduced to 50 to avoid rate limiting
                        )
                        if markets_resp.status_code != 200:
                            return None
                        raw_markets = markets_resp.json().get("markets", [])
                    except Exception:
                        return None

                    if not raw_markets:
                        return None

                    parsed_markets = []

                    for mkt in raw_markets:
                        market_id = mkt.get("id", "")
                        market_name = mkt.get("name", "")

                        # Classify market type - COMPREHENSIVE
                        market_type = None
                        name_lower = market_name.lower()

                        # PRIORITIZE Half/Quarter/Period Markets first
                        for period in ['1st quarter', '1st half', '1st set', 'first quarter', 'first half',
                                      'first set', '2nd quarter', '2nd half', '2nd set', 'second quarter',
                                      'second half', 'second set']:
                            if period in name_lower:
                                if any(kw in name_lower for kw in ['total points', 'total', 'over/under', 'over', 'under']):
                                    market_type = MarketType.TOTAL
                                elif any(kw in name_lower for kw in ['spread', 'handicap', 'line']):
                                    market_type = MarketType.SPREAD
                                else:
                                    # Default half/quarter markets to OTHER for now
                                    market_type = MarketType.OTHER
                                break

                        # If not a period-specific market, check main categories
                        if market_type is None:
                            # Player Props - EXTENSIVE KEYWORD MATCHING
                            player_keywords = [
                                # Scoring Props
                                'points', 'assists', 'rebounds', 'three pointers', '3-pointers', '3 pointers',
                                'touchdowns', 'rushing yards', 'passing yards', 'receiving yards', 'receptions',
                                'completions', 'interceptions', 'sacks', 'tackles', 'field goals', 'extra points',
                                # Basketball
                                'double-double', 'triple-double', 'assists + rebounds', 'points + rebounds',
                                'points + assists', 'points + rebounds + assists',
                                # Baseball
                                'hits', 'runs', 'home runs', 'rbi', 'stolen bases', 'strikeouts', 'bases on balls', 'walks',
                                'total bases', 'hits + runs + rbis', 'batting average',
                                # Soccer
                                'goals', 'shots on target', 'assists', 'cards', 'offsides', 'fouls',
                                # Tennis
                                'aces', 'double faults', 'break points', 'games won', 'sets won',
                                # Special Stats
                                'longest', 'first', 'last', 'anytime', 'score a', 'record', 'performance',
                                # Format indicators
                                ' over ', ' under ', 'vs', 'number'
                            ]

                            # Check if this is a player prop
                            if any(kw in name_lower for kw in player_keywords):
                                market_type = MarketType.PLAYER_PROP

                            # Team Props
                            elif any(kw in name_lower for kw in [
                                'team total', 'race to', 'highest scoring', 'margin',
                                'winning margin', 'first to score', 'last to score', 'clean sheet',
                                'to score first', 'to score last', 'both teams to score'
                            ]):
                                market_type = MarketType.TEAM_PROP

                            # Game Props
                            elif any(kw in name_lower for kw in [
                                'both teams to score', 'btts', 'correct score', 'draw no bet',
                                'double chance', 'total goals', 'match result', 'outright winner',
                                'extra innings', 'overtime', 'penalties'
                            ]):
                                market_type = MarketType.GAME_PROP

                            # Core Markets
                            elif "winner" in name_lower or "match odds" in name_lower or "moneyline" in name_lower or "to win" in name_lower or "1x2" in name_lower or "result" in name_lower:
                                market_type = MarketType.MONEYLINE

                            elif "spread" in name_lower or "handicap" in name_lower:
                                market_type = MarketType.SPREAD

                            elif "total" in name_lower or "over/under" in name_lower or ("over" in name_lower and "under" in name_lower):
                                market_type = MarketType.TOTAL

                            else:
                                # Unclassified - include as OTHER for comprehensive coverage
                                market_type = MarketType.OTHER

                        # Get contracts (outcomes)
                        try:
                            contracts_resp = await client.get(f"{BASE_URL}/markets/{market_id}/contracts/")
                            if contracts_resp.status_code == 429:  # Rate limited - skip this market
                                continue
                            if contracts_resp.status_code != 200:
                                continue
                            contracts = contracts_resp.json().get("contracts", [])
                        except Exception:
                            continue

                        if not contracts:
                            continue

                        # Get quotes (best prices)
                        try:
                            prices_resp = await client.get(f"{BASE_URL}/markets/{market_id}/quotes/")
                            if prices_resp.status_code == 429:  # Rate limited - skip this market
                                continue
                            if prices_resp.status_code != 200:
                                continue
                            quotes = prices_resp.json().get("quotes", {})
                        except Exception:
                            continue

                        outcomes = []
                        for contract in contracts:
                            contract_id = str(contract.get("id", ""))
                            contract_name = contract.get("name", "")

                            contract_quotes = quotes.get(contract_id, {})
                            best_back = contract_quotes.get("best_back_price")

                            if best_back:
                                try:
                                    decimal_odds = _percent_to_decimal(float(best_back))
                                    american_odds = _decimal_to_american(decimal_odds)

                                    if american_odds != 0:
                                        outcomes.append(Outcome(
                                            name=contract_name,
                                            price_american=american_odds,
                                            price_decimal=decimal_odds,
                                            description="Exchange back price",
                                        ))
                                except (ValueError, TypeError):
                                    pass

                        if outcomes:
                            parsed_markets.append(Market(
                                market_type=market_type,
                                name=market_name,
                                outcomes=outcomes,
                            ))

                    if not parsed_markets:
                        return None

                    # Determine league
                    league = ""
                    parent = ev_data.get("parent", {})
                    if parent:
                        league = parent.get("name", "")
                    if not league and full_slug:
                        parts = full_slug.split("/")
                        if len(parts) >= 3:
                            league = parts[2].replace("-", " ").title()
                    if not league:
                        league = sport.upper()

                    return Event(
                        event_id=str(event_id),
                        sport=sport,
                        league=league,
                        home_team=home_team,
                        away_team=away_team,
                        description=f"{away_team} @ {home_team}",
                        start_time=start_time,
                        is_live=is_live,
                        markets=parsed_markets,
                    )

            tasks = [process_event(ev) for ev in raw_events]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Event):
                    events.append(result)
                elif isinstance(result, Exception):
                    logger.debug(f"Smarkets event error: {result}")

    except Exception as e:
        logger.error(f"Smarkets error for {sport}: {e}")

    logger.info(f"Smarkets: {len(events)} {sport} events")

    if not events:
        return []

    return [SportsbookSnapshot(
        sportsbook="Smarkets",
        sport=sport,
        league=sport,
        fetched_at=datetime.now(timezone.utc),
        events=events,
    )]