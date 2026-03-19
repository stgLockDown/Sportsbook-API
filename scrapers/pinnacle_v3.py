"""
Pinnacle v3 (Arcadia) Scraper
Uses the guest Arcadia API to fetch matchups and straight markets.
Supports: Basketball (NBA, NCAA), Soccer, Tennis, Baseball, MMA
"""
import httpx
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Optional
from .models import SportsbookSnapshot, Event, Market, Outcome, MarketType

BASE = "https://guest.api.arcadia.pinnacle.com/0.1"

# Sport IDs in Pinnacle v3
SPORT_IDS = {
    "basketball_nba": 4,
    "basketball_ncaab": 4,
    "ice_hockey_nhl": 19,
    "baseball_mlb": 3,
    "football_nfl": 15,
    "soccer_epl": 29,
    "soccer_la_liga": 29,
    "soccer_bundesliga": 29,
    "soccer_serie_a": 29,
    "soccer_ligue_1": 29,
    "soccer_mls": 29,
    "soccer_champions_league": 29,
    "soccer_europa_league": 29,
    "soccer_world_cup": 29,
    "tennis": 33,
    "mma_ufc": 22,
}

# League IDs for filtering
LEAGUE_IDS = {
    "basketball_nba": [487],
    "basketball_ncaab": [493],
    "ice_hockey_nhl": [],  # Will use all hockey
    "baseball_mlb": [5425, 246],  # MLB + preseason
    "football_nfl": [],  # Will use all football
    "soccer_epl": [1980],
    "soccer_la_liga": [2196],
    "soccer_bundesliga": [1842],
    "soccer_serie_a": [2436],
    "soccer_ligue_1": [2036],
    "soccer_mls": [2663],
    "soccer_champions_league": [2627],
    "soccer_europa_league": [2630],
    "soccer_world_cup": [2686],
    "tennis": [],  # All tennis
    "mma_ufc": [1624],
}

LEAGUE_NAMES = {
    "basketball_nba": "NBA",
    "basketball_ncaab": "NCAA Basketball",
    "ice_hockey_nhl": "NHL",
    "baseball_mlb": "MLB",
    "football_nfl": "NFL",
    "soccer_epl": "English Premier League",
    "soccer_la_liga": "La Liga",
    "soccer_bundesliga": "Bundesliga",
    "soccer_serie_a": "Serie A",
    "soccer_ligue_1": "Ligue 1",
    "soccer_mls": "MLS",
    "soccer_champions_league": "Champions League",
    "soccer_europa_league": "Europa League",
    "soccer_world_cup": "World Cup",
    "tennis": "Tennis",
    "mma_ufc": "UFC",
}


def _american_to_decimal(american: int) -> float:
    """Convert American odds to decimal."""
    if american > 0:
        return round(1 + american / 100, 4)
    elif american < 0:
        return round(1 + 100 / abs(american), 4)
    return 1.0


def _parse_market_type(mtype: str) -> MarketType:
    """Map Pinnacle market type to our MarketType."""
    mapping = {
        "moneyline": MarketType.MONEYLINE,
        "spread": MarketType.SPREAD,
        "total": MarketType.TOTAL,
        "team_total": MarketType.TOTAL,
    }
    return mapping.get(mtype, MarketType.OTHER)


def _parse_market_name(mtype: str, period: int) -> str:
    """Generate human-readable market name."""
    period_str = ""
    if period == 1:
        period_str = " (1st Half)"
    elif period == 2:
        period_str = " (2nd Half)"
    elif period == 3:
        period_str = " (1st Period)"
    elif period == 4:
        period_str = " (2nd Period)"

    names = {
        "moneyline": f"Moneyline{period_str}",
        "spread": f"Spread{period_str}",
        "total": f"Total{period_str}",
        "team_total": f"Team Total{period_str}",
    }
    return names.get(mtype, f"{mtype}{period_str}")


async def _fetch_matchups(client: httpx.AsyncClient, sport_id: int, league_ids: List[int]) -> List[dict]:
    """Fetch matchups for a sport, optionally filtered by league."""
    all_matchups = []

    if league_ids:
        # Fetch per league for more targeted results
        for lid in league_ids:
            try:
                r = await client.get(f"{BASE}/leagues/{lid}/matchups", timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    matchups = [m for m in data if m.get("type") == "matchup"]
                    all_matchups.extend(matchups)
            except Exception:
                pass
            await asyncio.sleep(0.2)
    else:
        # Fetch all matchups for the sport
        try:
            r = await client.get(f"{BASE}/sports/{sport_id}/matchups", timeout=15)
            if r.status_code == 200:
                data = r.json()
                all_matchups = [m for m in data if m.get("type") == "matchup"]
        except Exception:
            pass

    return all_matchups


async def _fetch_markets(client: httpx.AsyncClient, sport_id: int) -> List[dict]:
    """Fetch straight markets for a sport."""
    try:
        r = await client.get(
            f"{BASE}/sports/{sport_id}/markets/straight",
            params={"primaryOnly": "true"},
            timeout=15,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


def _build_events(matchups: List[dict], markets: List[dict], sport: str, league_name: str, league_ids: List[int]) -> List[Event]:
    """Combine matchups and markets into Event objects."""
    # Index matchups by ID
    matchup_map: Dict[int, dict] = {}
    for m in matchups:
        matchup_map[m.get("id")] = m

    # Group markets by matchup ID
    markets_by_matchup: Dict[int, List[dict]] = {}
    for mkt in markets:
        mid = mkt.get("matchupId")
        if mid is not None:
            if mid not in markets_by_matchup:
                markets_by_matchup[mid] = []
            markets_by_matchup[mid].append(mkt)

    events = []
    # Only process matchups that have markets
    relevant_ids = set(matchup_map.keys()) & set(markets_by_matchup.keys())

    for mid in relevant_ids:
        matchup = matchup_map[mid]
        mkt_list = markets_by_matchup[mid]

        # Filter by league if needed
        if league_ids:
            matchup_league_id = matchup.get("league", {}).get("id")
            if matchup_league_id not in league_ids:
                continue

        # Extract participants
        participants = matchup.get("participants", [])
        home = ""
        away = ""
        for p in participants:
            alignment = p.get("alignment", "")
            name = p.get("name", "")
            if alignment == "home":
                home = name
            elif alignment == "away":
                away = name

        if not home and not away:
            if len(participants) >= 2:
                home = participants[0].get("name", "Team 1")
                away = participants[1].get("name", "Team 2")
            else:
                continue

        # Parse start time
        start_time = None
        start_str = matchup.get("startTime", "")
        if start_str:
            try:
                start_time = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            except Exception:
                pass

        is_live = matchup.get("isLive", False)

        # Build markets - only full game (period=0)
        event_markets = []
        for mkt in mkt_list:
            period = mkt.get("period", 0)
            if period != 0:
                continue  # Skip half/period markets for now

            mtype = mkt.get("type", "")
            prices = mkt.get("prices", [])
            if not prices:
                continue

            market_type = _parse_market_type(mtype)
            market_name = _parse_market_name(mtype, period)

            outcomes = []
            for price in prices:
                designation = price.get("designation", "")
                american = price.get("price")
                points = price.get("points")

                if american is None:
                    continue

                # Map designation to name
                if designation == "home":
                    oname = home
                elif designation == "away":
                    oname = away
                elif designation == "over":
                    oname = "Over"
                elif designation == "under":
                    oname = "Under"
                else:
                    oname = designation

                outcomes.append(Outcome(
                    name=oname,
                    price_american=int(american),
                    price_decimal=_american_to_decimal(int(american)),
                    point=float(points) if points is not None else None,
                ))

            if outcomes:
                event_markets.append(Market(
                    market_type=market_type,
                    name=market_name,
                    outcomes=outcomes,
                ))

        if not event_markets:
            continue

        matchup_league = matchup.get("league", {}).get("name", league_name)

        events.append(Event(
            event_id=f"pinnacle_v3_{mid}",
            sport=sport,
            league=matchup_league if not league_ids else league_name,
            home_team=home,
            away_team=away,
            description=f"{away} @ {home}",
            start_time=start_time,
            is_live=is_live,
            markets=event_markets,
        ))

    return events


async def fetch_sport(sport: str) -> List[SportsbookSnapshot]:
    """Fetch odds from Pinnacle v3 for a given sport key."""
    sport_id = SPORT_IDS.get(sport)
    if sport_id is None:
        return []

    league_ids = LEAGUE_IDS.get(sport, [])
    league_name = LEAGUE_NAMES.get(sport, sport)

    async with httpx.AsyncClient(
        headers={"Accept": "application/json"},
        follow_redirects=True,
    ) as client:
        # Fetch matchups and markets concurrently
        matchups_task = _fetch_matchups(client, sport_id, league_ids)
        markets_task = _fetch_markets(client, sport_id)
        matchups, markets = await asyncio.gather(matchups_task, markets_task)

        if not matchups or not markets:
            return []

        events = _build_events(matchups, markets, sport, league_name, league_ids)

        if not events:
            return []

        return [SportsbookSnapshot(
            sportsbook="pinnacle_v3",
            sport=sport,
            league=league_name,
            fetched_at=datetime.now(timezone.utc),
            events=events,
        )]


if __name__ == "__main__":
    async def test():
        for sport in ["basketball_nba", "soccer_epl", "tennis", "mma_ufc", "baseball_mlb"]:
            snapshots = await fetch_sport(sport)
            for snap in snapshots:
                print(f"\n{snap.sportsbook} | {sport}: {len(snap.events)} events")
                for ev in snap.events[:3]:
                    print(f"  {ev.description}")
                    for m in ev.markets:
                        outs = ", ".join(
                            f"{o.name}={o.price_american}" + (f" @{o.point}" if o.point else "")
                            for o in m.outcomes
                        )
                        print(f"    {m.name}: {outs}")

    asyncio.run(test())