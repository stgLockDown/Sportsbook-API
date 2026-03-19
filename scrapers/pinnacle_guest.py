"""
Pinnacle Guest API Scraper
Uses the guest.api.arcadia.pinnacle.com endpoint for matchups and straight markets.

This is a separate endpoint from Pinnacle v3, providing:
  - /0.1/sports -> all sports with matchup counts
  - /0.1/sports/{id}/matchups -> matchup list with team info
  - /0.1/sports/{id}/markets/straight -> all straight markets (ML, spread, total)
  
Odds are in American format. Matchups and markets are linked by matchupId.
"""

import asyncio
import httpx
from datetime import datetime, timezone
from typing import List, Optional, Dict, Tuple
from .models import SportsbookSnapshot, Event, Market, Outcome, MarketType

PINNACLE_GUEST_BASE = "https://guest.api.arcadia.pinnacle.com/0.1"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

# Sport ID mapping (Pinnacle sport IDs)
SPORT_MAP = {
    "basketball_nba": {"sport_id": 4, "sport_label": "Basketball", "league_label": "NBA", "league_ids": [487]},
    "basketball_ncaab": {"sport_id": 4, "sport_label": "Basketball", "league_label": "NCAAB", "league_ids": [493]},
    "football_nfl": {"sport_id": 15, "sport_label": "Football", "league_label": "NFL", "league_ids": [889]},
    "football_ncaaf": {"sport_id": 15, "sport_label": "Football", "league_label": "NCAAF", "league_ids": [880]},
    "baseball_mlb": {"sport_id": 3, "sport_label": "Baseball", "league_label": "MLB", "league_ids": [246]},
    "ice_hockey_nhl": {"sport_id": 19, "sport_label": "Hockey", "league_label": "NHL", "league_ids": [1456]},
    "soccer_epl": {"sport_id": 29, "sport_label": "Soccer", "league_label": "EPL", "league_ids": [1980]},
    "soccer": {"sport_id": 29, "sport_label": "Soccer", "league_label": "Soccer", "league_ids": []},
    "tennis": {"sport_id": 33, "sport_label": "Tennis", "league_label": "Tennis", "league_ids": []},
    "mma_ufc": {"sport_id": 22, "sport_label": "MMA", "league_label": "UFC", "league_ids": [1624]},
    "mma": {"sport_id": 22, "sport_label": "MMA", "league_label": "MMA", "league_ids": []},
    "boxing": {"sport_id": 6, "sport_label": "Boxing", "league_label": "Boxing", "league_ids": []},
    "golf": {"sport_id": 13, "sport_label": "Golf", "league_label": "Golf", "league_ids": []},
    "cricket": {"sport_id": 21, "sport_label": "Cricket", "league_label": "Cricket", "league_ids": []},
    "rugby_union": {"sport_id": 27, "sport_label": "Rugby", "league_label": "Rugby Union", "league_ids": []},
    "rugby_league": {"sport_id": 26, "sport_label": "Rugby League", "league_label": "Rugby League", "league_ids": []},
    "darts": {"sport_id": 7, "sport_label": "Darts", "league_label": "Darts", "league_ids": []},
    "table_tennis": {"sport_id": 32, "sport_label": "Table Tennis", "league_label": "Table Tennis", "league_ids": []},
    "volleyball": {"sport_id": 34, "sport_label": "Volleyball", "league_label": "Volleyball", "league_ids": []},
    "handball": {"sport_id": 18, "sport_label": "Handball", "league_label": "Handball", "league_ids": []},
    "esports": {"sport_id": 12, "sport_label": "Esports", "league_label": "Esports", "league_ids": []},
    "motor_sports": {"sport_id": 35, "sport_label": "Motor Sports", "league_label": "Motor Sports", "league_ids": []},
    "snooker": {"sport_id": 28, "sport_label": "Snooker", "league_label": "Snooker", "league_ids": []},
    "cycling": {"sport_id": 8, "sport_label": "Cycling", "league_label": "Cycling", "league_ids": []},
}


def _american_to_decimal(american: int) -> float:
    """Convert American odds to decimal."""
    if american > 0:
        return round(1 + american / 100, 3)
    elif american < 0:
        return round(1 + 100 / abs(american), 3)
    return 1.0


async def fetch_sport(sport_key: str) -> List[SportsbookSnapshot]:
    """
    Fetch odds from Pinnacle Guest API.
    
    Two-step approach:
    1. Get matchups for the sport (team names, start times)
    2. Get markets/straight for odds (ML, spread, total)
    3. Join on matchupId
    """
    mapping = SPORT_MAP.get(sport_key)
    if not mapping:
        return []

    sport_id = mapping["sport_id"]
    sport_label = mapping["sport_label"]
    league_label = mapping["league_label"]
    filter_league_ids = mapping.get("league_ids", [])

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        # Step 1: Fetch matchups
        matchups_url = f"{PINNACLE_GUEST_BASE}/sports/{sport_id}/matchups?withSpecials=false"
        try:
            resp = await client.get(matchups_url, headers=HEADERS)
            if resp.status_code != 200:
                return []
            matchups_data = resp.json()
        except Exception as e:
            print(f"[PinnacleGuest] Error fetching matchups: {e}")
            return []

        if not isinstance(matchups_data, list):
            return []

        # Step 2: Fetch straight markets
        markets_url = f"{PINNACLE_GUEST_BASE}/sports/{sport_id}/markets/straight"
        try:
            resp2 = await client.get(markets_url, headers=HEADERS)
            if resp2.status_code != 200:
                markets_data = []
            else:
                markets_data = resp2.json()
        except Exception:
            markets_data = []

        if not isinstance(markets_data, list):
            markets_data = []

        # Build market index by matchupId
        market_index: Dict[int, List[dict]] = {}
        for mkt in markets_data:
            mid = mkt.get("matchupId")
            if mid:
                if mid not in market_index:
                    market_index[mid] = []
                market_index[mid].append(mkt)

        # Parse matchups into events
        events = []
        for matchup in matchups_data:
            matchup_id = matchup.get("id")
            if not matchup_id:
                continue

            # Filter by league if specified
            league_info = matchup.get("league", {})
            league_id = league_info.get("id")
            if filter_league_ids and league_id not in filter_league_ids:
                continue

            # Skip specials (futures/props without participants)
            participants = matchup.get("participants", [])
            if not participants or len(participants) < 2:
                # Could be a special/future - check type
                special = matchup.get("special")
                if special:
                    continue
                # Skip if no participants
                if len(participants) < 2:
                    continue

            # Extract team names
            home = ""
            away = ""
            participant_map = {}  # participantId -> name
            designation_map = {}  # "home"/"away" -> name
            for p in participants:
                pid = p.get("id")
                pname = p.get("name", "")
                alignment = p.get("alignment", "")
                if pid:
                    participant_map[pid] = pname
                if alignment == "home":
                    home = pname
                    designation_map["home"] = pname
                elif alignment == "away":
                    away = pname
                    designation_map["away"] = pname

            # Fallback: first = away, second = home (Pinnacle convention)
            if not home and not away and len(participants) >= 2:
                away = participants[0].get("name", "")
                home = participants[1].get("name", "")
                designation_map["away"] = away
                designation_map["home"] = home

            if not home or not away:
                continue

            # Start time
            start_str = matchup.get("startTime")
            start_time = None
            if start_str:
                try:
                    start_time = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                except:
                    pass

            is_live = matchup.get("isLive", False)
            league_name = league_info.get("name", league_label)

            # Build markets from market_index
            event_markets = []
            raw_markets = market_index.get(matchup_id, [])
            
            for raw_mkt in raw_markets:
                mkt_type = raw_mkt.get("type", "")
                period = raw_mkt.get("period", 0)
                prices = raw_mkt.get("prices", [])
                is_alternate = raw_mkt.get("isAlternate", False)

                # Only main markets (period 0, not alternate)
                if period != 0 or is_alternate:
                    continue

                if not prices:
                    continue

                if mkt_type == "moneyline":
                    outcomes = []
                    for p in prices:
                        pid = p.get("participantId")
                        designation = p.get("designation", "")
                        price = p.get("price")
                        if price is None:
                            continue
                        # Resolve name: try participantId first, then designation map
                        name = participant_map.get(pid) if pid else None
                        if not name:
                            name = designation_map.get(designation, designation.capitalize() or "?")
                        dec = _american_to_decimal(price)
                        outcomes.append(Outcome(
                            name=name,
                            price_american=price,
                            price_decimal=dec,
                        ))
                    if len(outcomes) >= 2:
                        event_markets.append(Market(
                            market_type=MarketType.MONEYLINE,
                            name="Moneyline",
                            outcomes=outcomes,
                        ))

                elif mkt_type == "spread":
                    outcomes = []
                    for p in prices:
                        pid = p.get("participantId")
                        designation = p.get("designation", "")
                        price = p.get("price")
                        points = p.get("points")
                        if price is None:
                            continue
                        name = participant_map.get(pid) if pid else None
                        if not name:
                            name = designation_map.get(designation, designation.capitalize() or "?")
                        dec = _american_to_decimal(price)
                        outcomes.append(Outcome(
                            name=name,
                            price_american=price,
                            price_decimal=dec,
                            point=points,
                        ))
                    if len(outcomes) >= 2:
                        event_markets.append(Market(
                            market_type=MarketType.SPREAD,
                            name="Spread",
                            outcomes=outcomes,
                        ))

                elif mkt_type == "total":
                    outcomes = []
                    for p in prices:
                        designation = p.get("designation", "")
                        price = p.get("price")
                        points = p.get("points")
                        if price is None:
                            continue
                        name = designation.capitalize() if designation else "?"
                        dec = _american_to_decimal(price)
                        outcomes.append(Outcome(
                            name=name,
                            price_american=price,
                            price_decimal=dec,
                            point=points,
                        ))
                    if len(outcomes) >= 2:
                        event_markets.append(Market(
                            market_type=MarketType.TOTAL,
                            name="Total",
                            outcomes=outcomes,
                        ))

            events.append(Event(
                event_id=str(matchup_id),
                sport=sport_label,
                league=league_name if not filter_league_ids else league_label,
                home_team=home,
                away_team=away,
                description=f"{away} @ {home}",
                start_time=start_time,
                is_live=is_live,
                markets=event_markets,
            ))

    if not events:
        return []

    return [SportsbookSnapshot(
        sportsbook="Pinnacle (Guest)",
        sport=sport_label,
        league=league_label,
        fetched_at=datetime.now(timezone.utc),
        events=events,
    )]