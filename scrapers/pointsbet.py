"""
PointsBet Scraper — US sportsbook with deep market coverage.

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

# ── Competition IDs ─────────────────────────────────────────────────
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


def _parse_markets_from_detail(detail: dict) -> List[Market]:
    """Parse markets from PointsBet event detail response."""
    markets: List[Market] = []
    fom = detail.get("fixedOddsMarkets", [])

    for m in fom:
        market_name = m.get("eventName", m.get("name", ""))
        outcomes_raw = m.get("outcomes", [])
        if not outcomes_raw:
            continue

        # Determine market type from name
        name_lower = market_name.lower()
        if "moneyline" in name_lower or "money line" in name_lower or "match result" in name_lower:
            mtype = MarketType.MONEYLINE
        elif "spread" in name_lower or "handicap" in name_lower:
            mtype = MarketType.SPREAD
        elif "total" in name_lower and ("over" in name_lower or "under" in name_lower or
              any("over" in o.get("name", "").lower() or "under" in o.get("name", "").lower() for o in outcomes_raw)):
            mtype = MarketType.TOTAL
        elif "player" in name_lower or "pts" in name_lower or "reb" in name_lower or "ast" in name_lower:
            mtype = MarketType.PLAYER_PROP
        else:
            mtype = MarketType.OTHER

        # Only include main markets (ML, spread, total) to keep response size manageable
        if mtype not in (MarketType.MONEYLINE, MarketType.SPREAD, MarketType.TOTAL):
            continue

        # Skip alternate lines (keep only primary markets with 2 outcomes)
        if mtype in (MarketType.SPREAD, MarketType.TOTAL) and len(outcomes_raw) > 2:
            # This is an alternate lines market, skip it
            continue

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
                market_type=mtype,
                name=market_name,
                outcomes=outcomes,
            ))

    return markets


async def fetch_sport(sport: str) -> List[SportsbookSnapshot]:
    """Fetch odds from PointsBet for a given sport."""
    comp_id = COMPETITION_IDS.get(sport)
    if comp_id is None:
        return []

    async with httpx.AsyncClient(timeout=20, headers=HEADERS) as client:
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


# ── Test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    async def _test():
        for sport in ["basketball_nba", "ice_hockey_nhl", "baseball_mlb",
                       "american_football_nfl", "soccer_epl"]:
            print(f"\n{'='*60}")
            print(f"Sport: {sport}")
            print(f"{'='*60}")
            snaps = await fetch_sport(sport)
            for s in snaps:
                print(f"  {s.sportsbook}: {len(s.events)} events")
                for ev in s.events[:3]:
                    live_tag = " [LIVE]" if ev.is_live else ""
                    print(f"    {ev.away_team} @ {ev.home_team}{live_tag}")
                    for m in ev.markets[:5]:
                        outs = ", ".join([f"{o.name}: {o.price_decimal} ({o.price_american})" for o in m.outcomes])
                        print(f"      {m.market_type.value}: {outs}")
    asyncio.run(_test())