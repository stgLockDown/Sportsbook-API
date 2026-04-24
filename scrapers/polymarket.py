"""
Polymarket Prediction Market Scraper
=====================================
Polymarket is a crypto-based prediction market with extensive sports coverage.
Uses USDC stablecoin for all bets. Markets are decentralized on Polygon blockchain.

API: https://gamma-api.polymarket.com/events
No authentication required for public market data.

Each event has multiple markets. Markets have 2 outcomes (Yes/No) with prices.
Prices are in decimal 0-1 representing implied probability.
"""

import httpx
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict
from scrapers.models import SportsbookSnapshot, Event, Market, Outcome, MarketType

logger = logging.getLogger(__name__)

BASE_URL = "https://gamma-api.polymarket.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# Sport keyword → Polymarket tag/category filters
SPORT_FILTERS = {
    "basketball_nba": ["NBA", "basketball"],
    "basketball_ncaab": ["NCAAB", "March Madness", "college basketball"],
    "basketball_wnba": ["WNBA"],
    "football_nfl": ["NFL", "Super Bowl"],
    "football_ncaaf": ["NCAAF", "college football"],
    "baseball_mlb": ["MLB", "baseball", "World Series"],
    "ice_hockey_nhl": ["NHL", "hockey", "Stanley Cup"],
    "soccer": ["soccer", "EPL", "UCL", "MLS", "La Liga", "Bundesliga", "World Cup"],
    "tennis": ["tennis", "ATP", "WTA", "US Open", "Wimbledon", "Australian Open"],
    "mma": ["UFC", "MMA"],
    "boxing": ["boxing"],
    "golf": ["PGA", "golf", "Masters"],
    "cricket": ["cricket", "IPL"],
    "esports": ["esports", "Valorant", "LoL", "CSGO", "CS:GO", "Dota"],
    "motorsport": ["F1", "Formula 1", "NASCAR", "IndyCar"],
}


def _decimal_prob_to_decimal_odds(prob: Optional[float]) -> Optional[float]:
    """Convert probability (0-1) to decimal odds."""
    if prob is None or prob <= 0 or prob >= 1:
        return None
    return round(1.0 / prob, 4)


def _decimal_to_american(decimal_odds: Optional[float]) -> Optional[int]:
    """Convert decimal odds to American format."""
    if decimal_odds is None or decimal_odds <= 1.0:
        return None
    if decimal_odds >= 2.0:
        return int(round((decimal_odds - 1) * 100))
    return int(round(-100 / (decimal_odds - 1)))


def _classify_market_title(title: str) -> MarketType:
    """Classify Polymarket market into MarketType enum."""
    t = title.lower()
    if any(x in t for x in ["win", "beat", "defeat"]) and any(x in t for x in ["game", "match"]):
        return MarketType.MONEYLINE
    if "spread" in t or ("beat" in t and ("point" in t or "by" in t)):
        return MarketType.SPREAD
    if any(x in t for x in ["over/under", "total points", "combined", "total runs", "total goals"]):
        return MarketType.TOTAL
    if "championship" in t or "series" in t or "playoffs" in t or "season" in t or "mvp" in t:
        return MarketType.FUTURES
    if any(x in t for x in ["score", "yards", "points", "rebounds", "assists", "touchdown", "home run", "player"]):
        return MarketType.PLAYER_PROP
    return MarketType.OTHER


async def _fetch_events(client: httpx.AsyncClient, sport: str) -> List[dict]:
    """Fetch Polymarket events filtered by sport category."""
    all_events = []
    offset = 0
    limit = 100
    max_pages = 5
    
    for _ in range(max_pages):
        try:
            params = {
                "limit": limit,
                "offset": offset,
                "active": "true",
                "closed": "false",
                "order": "volume24hr",
                "ascending": "false",
            }
            resp = await client.get(f"{BASE_URL}/events", params=params)
            if resp.status_code != 200:
                break
            
            data = resp.json()
            if not isinstance(data, list):
                break
            
            events = data
            if not events:
                break
            
            all_events.extend(events)
            
            if len(events) < limit:
                break
            offset += limit
        except Exception as e:
            logger.debug(f"Polymarket events fetch error: {e}")
            break
    
    # Filter by sport category
    sport_filters = SPORT_FILTERS.get(sport, [])
    if sport_filters:
        filtered = []
        for ev in all_events:
            category = ev.get("category", "")
            title = ev.get("title", "")
            tags = " ".join([tag.get("label", "") for tag in ev.get("tags", [])])
            search_text = f"{category} {title} {tags}".lower()
            
            if category.lower() == "sports" or any(kw.lower() in search_text for kw in sport_filters):
                filtered.append(ev)
        return filtered
    
    # Default: return sports events
    return [e for e in all_events if e.get("category", "").lower() == "sports"]


def _parse_polymarket_event(event_data: dict, sport: str) -> Optional[Event]:
    """Parse a Polymarket event into our Event model."""
    event_id = str(event_data.get("id", ""))
    title = event_data.get("title", "")
    description = event_data.get("description", "")
    
    # Parse dates
    start_time = None
    for key in ["startDate", "creationDate", "published_at"]:
        val = event_data.get(key)
        if val:
            try:
                if isinstance(val, str):
                    start_time = datetime.fromisoformat(val.replace("Z", "+00:00"))
                    break
            except Exception:
                pass
    
    # Check if event is still active
    if event_data.get("closed") or event_data.get("archived"):
        return None
    
    markets_raw = event_data.get("markets", [])
    markets: List[Market] = []
    
    for mkt in markets_raw:
        if mkt.get("closed") or mkt.get("archived"):
            continue
        
        question = mkt.get("question", "") or mkt.get("groupItemTitle", "") or title
        
        # Polymarket markets have outcomes with prices
        outcomes_data = mkt.get("outcomes", "[]")
        outcome_prices = mkt.get("outcomePrices", "[]")
        
        # Parse JSON-encoded strings
        try:
            if isinstance(outcomes_data, str):
                outcomes_list = json.loads(outcomes_data)
            else:
                outcomes_list = outcomes_data or []
            
            if isinstance(outcome_prices, str):
                prices_list = json.loads(outcome_prices)
            else:
                prices_list = outcome_prices or []
        except (json.JSONDecodeError, ValueError):
            continue
        
        if not outcomes_list or not prices_list:
            continue
        
        if len(outcomes_list) != len(prices_list):
            continue
        
        outcomes: List[Outcome] = []
        for name, price_str in zip(outcomes_list, prices_list):
            try:
                prob = float(price_str)
            except (ValueError, TypeError):
                continue
            
            if prob <= 0 or prob >= 1:
                continue
            
            dec = _decimal_prob_to_decimal_odds(prob)
            outcomes.append(Outcome(
                name=str(name),
                price_decimal=dec,
                price_american=_decimal_to_american(dec),
                description=f"Buy at {prob*100:.1f}¢",
            ))
        
        if not outcomes:
            continue
        
        markets.append(Market(
            market_type=_classify_market_title(question),
            name=question[:150],
            outcomes=outcomes,
        ))
    
    if not markets:
        return None
    
    # Try to extract team names
    home_team = title[:80]
    away_team = ""
    
    # Look for "vs", "@", "and" in title
    for sep in [" vs ", " vs. ", " @ ", " at ", " and "]:
        if sep in title:
            parts = title.split(sep, 1)
            if len(parts) == 2:
                home_team = parts[0].strip()[:50]
                away_team = parts[1].strip()[:50]
                break
    
    return Event(
        event_id=f"polymarket_{event_id}",
        sport=sport,
        league=event_data.get("category", sport.upper()),
        home_team=home_team,
        away_team=away_team,
        description=title,
        start_time=start_time,
        is_live=False,
        markets=markets,
    )


async def fetch_sport(sport: str) -> List[SportsbookSnapshot]:
    """Fetch Polymarket events for a given sport."""
    async with httpx.AsyncClient(timeout=25, headers=HEADERS) as client:
        events_raw = await _fetch_events(client, sport)
        
        if not events_raw:
            return []
        
        events: List[Event] = []
        for ev_raw in events_raw[:100]:  # Limit for performance
            parsed = _parse_polymarket_event(ev_raw, sport)
            if parsed:
                events.append(parsed)
        
        if not events:
            return []
        
        return [SportsbookSnapshot(
            sportsbook="Polymarket",
            sport=sport,
            league=sport.upper(),
            fetched_at=datetime.now(timezone.utc),
            events=events,
        )]


# ─── Test ─────────────────────────────────────────────────────
if __name__ == "__main__":
    async def _test():
        for sport in ["football_nfl", "basketball_nba", "soccer"]:
            print(f"\n{'='*60}")
            print(f"Polymarket: {sport}")
            print(f"{'='*60}")
            snaps = await fetch_sport(sport)
            for snap in snaps:
                print(f"Events: {len(snap.events)}")
                total_markets = sum(len(e.markets) for e in snap.events)
                print(f"Total Markets: {total_markets}")
                if snap.events:
                    ev = snap.events[0]
                    print(f"Sample: {ev.description[:100]}")
                    for m in ev.markets[:3]:
                        print(f"  {m.market_type.value}: {m.name[:80]}")
                        for o in m.outcomes[:3]:
                            print(f"    {o.name}: dec={o.price_decimal} amer={o.price_american}")
    
    asyncio.run(_test())