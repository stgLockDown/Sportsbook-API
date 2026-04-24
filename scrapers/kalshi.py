"""
Kalshi Prediction Market Scraper
=================================
Kalshi is a CFTC-regulated US prediction market offering sports event contracts.

API: https://api.elections.kalshi.com/trade-api/v2/
No authentication required for public market data.

Strategy:
  1. Fetch /markets?category=Sports&status=open to get all sports markets
  2. Group markets by event_ticker
  3. Fetch event details (with nested markets) for grouping
  4. Parse YES/NO prices as Decimal/American odds
"""

import httpx
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import List, Optional, Dict
from scrapers.models import SportsbookSnapshot, Event, Market, Outcome, MarketType

logger = logging.getLogger(__name__)

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# Sport keyword → Kalshi ticker prefix match (used to filter markets)
SPORT_TICKERS = {
    "basketball_nba": ["NBA", "KXNBA", "KXNBAGAME", "KXNBAPTS", "KXNBAREB", "KXNBAAST"],
    "basketball_ncaab": ["NCAAB", "KXNCAAB", "CBB"],
    "basketball_wnba": ["WNBA", "KXWNBA"],
    "football_nfl": ["NFL", "KXNFL"],
    "football_ncaaf": ["NCAAF", "KXNCAAF", "CFB"],
    "baseball_mlb": ["MLB", "KXMLB", "KXMLBGAME"],
    "ice_hockey_nhl": ["NHL", "KXNHL"],
    "soccer": ["SOCCER", "EPL", "UCL", "MLS", "LALIGA", "BUNDES"],
    "tennis": ["TENNIS", "ATP", "WTA"],
    "mma": ["UFC", "MMA", "KXUFC"],
    "boxing": ["BOXING"],
    "golf": ["PGA", "GOLF", "MASTERS"],
    "cricket": ["CRICKET", "IPL"],
    "esports": ["ESPORTS", "VALORANT", "LOL", "CSGO"],
    "motorsport": ["F1", "NASCAR"],
}


def _cents_to_decimal(cents: Optional[float]) -> Optional[float]:
    """Convert price in cents (0-100) to decimal odds."""
    if cents is None or cents <= 0 or cents >= 100:
        return None
    return round(100.0 / cents, 4)


def _decimal_to_american(decimal_odds: Optional[float]) -> Optional[int]:
    """Convert decimal odds to American format."""
    if decimal_odds is None or decimal_odds <= 1.0:
        return None
    if decimal_odds >= 2.0:
        return int(round((decimal_odds - 1) * 100))
    return int(round(-100 / (decimal_odds - 1)))


def _classify_ticker(ticker: str) -> MarketType:
    """Classify market type based on Kalshi ticker prefix."""
    t = ticker.upper()
    if "GAME" in t:
        return MarketType.MONEYLINE
    if "PTS" in t or "POINTS" in t:
        return MarketType.PLAYER_PROP
    if "REB" in t or "AST" in t or "STL" in t or "BLK" in t:
        return MarketType.PLAYER_PROP
    if "YARDS" in t or "TOUCHDOWN" in t or "PASS" in t:
        return MarketType.PLAYER_PROP
    if "HR" in t or "RBI" in t or "STRIKEOUT" in t or "HITS" in t:
        return MarketType.PLAYER_PROP
    if "GOAL" in t or "ASSIST" in t:
        return MarketType.PLAYER_PROP
    if "CHAMPION" in t or "SERIES" in t or "SEASON" in t or "MVP" in t:
        return MarketType.FUTURES
    if "SPREAD" in t:
        return MarketType.SPREAD
    if "TOTAL" in t or "OU" in t:
        return MarketType.TOTAL
    return MarketType.OTHER


def _matches_sport(ticker: str, event_ticker: str, sport: str) -> bool:
    """Check if a market's ticker matches the requested sport."""
    if sport not in SPORT_TICKERS:
        return True  # No filter
    patterns = SPORT_TICKERS[sport]
    combined = f"{ticker} {event_ticker}".upper()
    return any(p.upper() in combined for p in patterns)


async def _fetch_all_sports_markets(client: httpx.AsyncClient, sport: str) -> List[dict]:
    """Fetch all sports markets, paginating through results."""
    all_markets = []
    cursor = None
    max_pages = 10  # Limit pages
    
    for _ in range(max_pages):
        try:
            params = {
                "category": "Sports",
                "status": "open",
                "limit": 1000,  # Max per page
            }
            if cursor:
                params["cursor"] = cursor
            
            resp = await client.get(f"{BASE_URL}/markets", params=params)
            if resp.status_code != 200:
                break
            
            data = resp.json()
            markets = data.get("markets", [])
            if not markets:
                break
            
            all_markets.extend(markets)
            cursor = data.get("cursor")
            if not cursor:
                break
        except Exception as e:
            logger.debug(f"Kalshi markets fetch error: {e}")
            break
    
    # Filter by sport
    filtered = []
    for mkt in all_markets:
        ticker = mkt.get("ticker", "")
        event_ticker = mkt.get("event_ticker", "")
        if _matches_sport(ticker, event_ticker, sport):
            filtered.append(mkt)
    
    return filtered


def _parse_kalshi_market(market: dict) -> Optional[Market]:
    """Parse a Kalshi market into our Market model."""
    ticker = market.get("ticker", "")
    title = (market.get("title", "") or market.get("yes_sub_title", "") 
             or market.get("subtitle", "") or ticker)
    
    # Get YES and NO prices (in cents, 0-100)
    yes_bid = market.get("yes_bid")
    yes_ask = market.get("yes_ask")
    no_bid = market.get("no_bid")
    no_ask = market.get("no_ask")
    
    # Some markets use "last_price_dollars"
    last_price_dollars = market.get("last_price_dollars")
    try:
        last_price = float(last_price_dollars) * 100 if last_price_dollars else None
    except (ValueError, TypeError):
        last_price = market.get("last_price")
    
    # Use best ask (buying price) - prefer actual asks
    yes_price = yes_ask or last_price
    no_price = no_ask or (100 - last_price if last_price else None)
    
    if yes_price is None or yes_price <= 0:
        return None
    
    outcomes = []
    dec_yes = _cents_to_decimal(yes_price)
    if dec_yes:
        outcomes.append(Outcome(
            name="Yes",
            price_decimal=dec_yes,
            price_american=_decimal_to_american(dec_yes),
            description=f"Buy YES at {yes_price:.0f}¢",
        ))
    
    if no_price and no_price > 0:
        dec_no = _cents_to_decimal(no_price)
        if dec_no:
            outcomes.append(Outcome(
                name="No",
                price_decimal=dec_no,
                price_american=_decimal_to_american(dec_no),
                description=f"Buy NO at {no_price:.0f}¢",
            ))
    
    if not outcomes:
        return None
    
    return Market(
        market_type=_classify_ticker(ticker),
        name=title[:150],
        outcomes=outcomes,
    )


async def fetch_sport(sport: str) -> List[SportsbookSnapshot]:
    """Fetch Kalshi sports markets, grouped by event."""
    async with httpx.AsyncClient(timeout=25, headers=HEADERS) as client:
        markets_raw = await _fetch_all_sports_markets(client, sport)
        
        if not markets_raw:
            return []
        
        # Group markets by event_ticker
        events_by_ticker: Dict[str, List[dict]] = defaultdict(list)
        for mkt in markets_raw:
            event_ticker = mkt.get("event_ticker", "")
            if event_ticker:
                events_by_ticker[event_ticker].append(mkt)
        
        events: List[Event] = []
        for event_ticker, event_markets in events_by_ticker.items():
            if not event_markets:
                continue
            
            # Parse markets
            markets: List[Market] = []
            for mkt in event_markets:
                parsed = _parse_kalshi_market(mkt)
                if parsed:
                    markets.append(parsed)
            
            if not markets:
                continue
            
            # Extract event title from first market
            first = event_markets[0]
            title = (first.get("title", "") or first.get("yes_sub_title", "")
                     or first.get("subtitle", "") or event_ticker)
            
            # Parse close time
            start_time = None
            close_time = first.get("close_time")
            if close_time:
                try:
                    start_time = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
                except Exception:
                    pass
            
            # Extract home/away teams from ticker (e.g., KXMLBGAME-26APR241915PHIATL)
            home_team = ""
            away_team = ""
            parts = event_ticker.split("-")
            if len(parts) >= 2:
                last_part = parts[-1]
                # Try to extract two 3-letter team codes
                if len(last_part) >= 6 and last_part[-6:].isalpha():
                    teams_code = last_part[-6:]
                    away_team = teams_code[:3]
                    home_team = teams_code[3:]
            
            if not home_team:
                home_team = title[:60]
                away_team = ""
            
            events.append(Event(
                event_id=f"kalshi_{event_ticker}",
                sport=sport,
                league=event_ticker.split("-")[0] if "-" in event_ticker else sport.upper(),
                home_team=home_team,
                away_team=away_team,
                description=title[:200],
                start_time=start_time,
                is_live=False,
                markets=markets,
            ))
        
        if not events:
            return []
        
        return [SportsbookSnapshot(
            sportsbook="Kalshi",
            sport=sport,
            league=sport.upper(),
            fetched_at=datetime.now(timezone.utc),
            events=events,
        )]


# ─── Test ─────────────────────────────────────────────────────
if __name__ == "__main__":
    async def _test():
        for sport in ["football_nfl", "basketball_nba", "baseball_mlb"]:
            print(f"\n{'='*60}")
            print(f"Kalshi: {sport}")
            print(f"{'='*60}")
            snaps = await fetch_sport(sport)
            for snap in snaps:
                total_markets = sum(len(e.markets) for e in snap.events)
                print(f"Events: {len(snap.events)}, Total Markets: {total_markets}")
                if snap.events:
                    ev = snap.events[0]
                    print(f"Sample: {ev.description[:100]}")
                    for m in ev.markets[:3]:
                        print(f"  {m.market_type.value}: {m.name[:80]}")
                        for o in m.outcomes:
                            print(f"    {o.name}: dec={o.price_decimal} amer={o.price_american}")
    
    asyncio.run(_test())