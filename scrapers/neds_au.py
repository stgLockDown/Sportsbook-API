"""
Neds AU scraper — Entain platform (same as Ladbrokes AU but different brand).
Returns events with full odds (fractional → decimal → American).
"""
import httpx
from datetime import datetime, timezone
from typing import List
from .models import SportsbookSnapshot, Event, Market, Outcome, MarketType
from .ladbrokes_au import (
    _fractional_to_decimal, _decimal_to_american, _classify_market, _match_sport
)

BASE_URL = "https://api.neds.com.au/v2/sport"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Referer": "https://www.neds.com.au",
    "Origin": "https://www.neds.com.au",
}


async def fetch_sport(sport: str) -> List[SportsbookSnapshot]:
    """Fetch odds for a sport from Neds AU."""
    async with httpx.AsyncClient(timeout=25) as client:
        try:
            r = await client.get(
                f"{BASE_URL}/event-request?category_id=6",
                headers=HEADERS,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"[Neds AU] Error fetching data: {e}")
            return []

    raw_events = data.get("events", {})
    raw_markets = data.get("markets", {})
    raw_prices = data.get("prices", {})
    raw_entrants = data.get("entrants", {})

    # Build entrant → price lookup
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

        if not _match_sport(comp_name, sport):
            continue

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

        start_str = ev.get("advertised_start", "")
        start_time = None
        if start_str:
            try:
                start_time = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            except:
                pass

        is_live = ev.get("match_status", "") in ("InProgress", "Live")

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

                price_data = entrant_prices.get(ent_id, {})
                odds = price_data.get("odds", {})
                num = odds.get("numerator", 0)
                den = odds.get("denominator", 1)

                if den == 0:
                    continue

                decimal_odds = _fractional_to_decimal(num, den)
                american_odds = _decimal_to_american(decimal_odds)

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

    snapshots = []
    if events:
        snapshots.append(SportsbookSnapshot(
            sportsbook="Neds AU",
            sport=sport,
            league=sport.upper(),
            events=events,
            fetched_at=datetime.now(timezone.utc),
        ))

    return snapshots