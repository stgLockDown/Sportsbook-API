"""
Pinnacle Sportsbook Scraper
Directly hits Pinnacle's public Arcadia API for odds data.
Pinnacle is one of the sharpest books - their odds are considered market-setting.
"""

import httpx
from datetime import datetime, timezone
from typing import List, Optional, Dict, Tuple
from .models import (
    SportsbookSnapshot, Event, Market, Outcome, MarketType
)

SPORTSBOOK_NAME = "Pinnacle"

BASE_URL = "https://guest.api.arcadia.pinnacle.com/0.1"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.pinnacle.com/",
    "Origin": "https://www.pinnacle.com",
    "X-API-Key": "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R",
}

# Pinnacle sport IDs
SPORT_IDS = {
    "basketball": 4,
    "football": 15,
    "hockey": 19,
    "baseball": 3,
    "soccer": 29,
    "tennis": 33,
    "golf": 17,
    "mma": 22,
    "boxing": 6,
}

# Key league IDs for US sports
LEAGUE_IDS = {
    # Basketball
    "NBA": 487,
    "NCAAB": 493,
    "WNBA": 578,
    # Football
    "NFL": 889,
    "NCAAF": 880,
    # Hockey
    "NHL": 1456,
    # Baseball
    "MLB": 246,
    # Soccer
    "MLS": 2663,
    "EPL": 1980,
    "La Liga": 2196,
    "Bundesliga": 1842,
    "Serie A": 2436,
    "Ligue 1": 2036,
    "Champions League": 2627,
    # MMA
    "UFC": 1624,
}

# Map sport IDs to our normalized sport names
SPORT_ID_TO_NAME = {
    3: "Baseball",
    4: "Basketball",
    6: "Boxing",
    15: "Football",
    17: "Golf",
    19: "Hockey",
    22: "MMA",
    29: "Soccer",
    33: "Tennis",
}


def _classify_market_type(pinnacle_type: str) -> MarketType:
    """Map Pinnacle market type to our standard type."""
    mapping = {
        "moneyline": MarketType.MONEYLINE,
        "spread": MarketType.SPREAD,
        "total": MarketType.TOTAL,
        "team_total": MarketType.TOTAL,
    }
    return mapping.get(pinnacle_type, MarketType.OTHER)


def _parse_matchups_and_markets(
    matchups: List[dict],
    markets: List[dict],
    sport_name: str,
) -> List[Event]:
    """Parse Pinnacle matchups and markets into Event models."""

    # Separate game matchups from specials (player props)
    game_matchups = {}  # id -> matchup data
    special_matchups = {}  # id -> matchup data

    for m in matchups:
        mid = m.get("id")
        mtype = m.get("type", "")

        if mtype == "special":
            special_matchups[mid] = m
        elif mtype == "matchup":
            participants = m.get("participants", [])
            home_team = ""
            away_team = ""
            for p in participants:
                alignment = p.get("alignment", "")
                name = p.get("name", "")
                if alignment == "home":
                    home_team = name
                elif alignment == "away":
                    away_team = name

            start_time = None
            raw_time = m.get("startTime", "")
            if raw_time:
                try:
                    start_time = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass

            league_info = m.get("league", {}) or {}

            game_matchups[mid] = {
                "home_team": home_team,
                "away_team": away_team,
                "start_time": start_time,
                "is_live": m.get("isLive", False),
                "league_name": league_info.get("name", ""),
                "league_group": league_info.get("group", ""),
                "league_id": league_info.get("id"),
            }

    # Build matchupId -> markets mapping
    matchup_markets: Dict[int, List[dict]] = {}
    for mkt in markets:
        mid = mkt.get("matchupId")
        if mid is not None:
            if mid not in matchup_markets:
                matchup_markets[mid] = []
            matchup_markets[mid].append(mkt)

    # Build events from game matchups
    events = []
    for mid, info in game_matchups.items():
        raw_markets = matchup_markets.get(mid, [])
        if not raw_markets:
            continue

        # Parse markets - only include non-alternate, full-game (period 0) by default
        parsed_markets = []
        for raw_mkt in raw_markets:
            period = raw_mkt.get("period", 0)
            is_alternate = raw_mkt.get("isAlternate", False)
            status = raw_mkt.get("status", "")
            mkt_type_str = raw_mkt.get("type", "")

            if status != "open":
                continue

            market_type = _classify_market_type(mkt_type_str)

            # Build market name
            period_label = ""
            if period == 0:
                period_label = "Full Game"
            elif period == 1:
                period_label = "1st Half"
            elif period == 3:
                period_label = "1st Quarter"
            elif period == 4:
                period_label = "2nd Quarter"
            else:
                period_label = f"Period {period}"

            alt_label = " (Alt)" if is_alternate else ""
            market_name = f"{mkt_type_str.replace('_', ' ').title()} - {period_label}{alt_label}"

            # Parse prices/outcomes
            outcomes = []
            for price_data in raw_mkt.get("prices", []):
                designation = price_data.get("designation", "")
                american_price = price_data.get("price")
                points = price_data.get("points")
                participant_id = price_data.get("participantId")

                # Determine outcome name
                if designation == "home":
                    outcome_name = info["home_team"] or "Home"
                elif designation == "away":
                    outcome_name = info["away_team"] or "Away"
                elif designation == "over":
                    outcome_name = "Over"
                elif designation == "under":
                    outcome_name = "Under"
                elif designation == "draw":
                    outcome_name = "Draw"
                else:
                    outcome_name = designation.title() if designation else "Unknown"

                # Convert American odds to decimal
                decimal_val = None
                if american_price is not None:
                    try:
                        if american_price > 0:
                            decimal_val = round(1 + (american_price / 100), 4)
                        elif american_price < 0:
                            decimal_val = round(1 + (100 / abs(american_price)), 4)
                        else:
                            decimal_val = 2.0
                    except (ZeroDivisionError, TypeError):
                        pass

                point_val = None
                if points is not None:
                    try:
                        point_val = float(points)
                    except (ValueError, TypeError):
                        pass

                if american_price is not None:
                    outcomes.append(Outcome(
                        name=outcome_name,
                        price_american=int(american_price),
                        price_decimal=decimal_val,
                        point=point_val,
                    ))

            if outcomes:
                parsed_markets.append(Market(
                    market_type=market_type,
                    name=market_name,
                    outcomes=outcomes,
                ))

        if parsed_markets:
            league_name = info["league_name"] or sport_name
            events.append(Event(
                event_id=str(mid),
                sport=sport_name,
                league=league_name,
                home_team=info["home_team"],
                away_team=info["away_team"],
                description=f"{info['away_team']} @ {info['home_team']}" if info["away_team"] else info["home_team"],
                start_time=info["start_time"],
                is_live=info["is_live"],
                markets=parsed_markets,
            ))

    return events


async def fetch_sport(sport_key: str, client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    """Fetch odds for a sport from Pinnacle."""
    close_client = False
    if client is None:
        client = httpx.AsyncClient(headers=HEADERS, timeout=30.0)
        close_client = True

    snapshots = []
    sport_id = SPORT_IDS.get(sport_key.lower())
    if not sport_id:
        return []

    sport_name = SPORT_ID_TO_NAME.get(sport_id, sport_key.title())

    try:
        # Fetch matchups
        matchups_resp = await client.get(f"{BASE_URL}/sports/{sport_id}/matchups")
        matchups_resp.raise_for_status()
        matchups = matchups_resp.json()

        # Fetch markets
        markets_resp = await client.get(f"{BASE_URL}/sports/{sport_id}/markets/straight")
        markets_resp.raise_for_status()
        markets = markets_resp.json()

        events = _parse_matchups_and_markets(matchups, markets, sport_name)
        now = datetime.now(timezone.utc)

        # Group events by league
        league_events: Dict[str, List[Event]] = {}
        for ev in events:
            if ev.league not in league_events:
                league_events[ev.league] = []
            league_events[ev.league].append(ev)

        for league_name, levents in league_events.items():
            snapshots.append(SportsbookSnapshot(
                sportsbook=SPORTSBOOK_NAME,
                sport=sport_name,
                league=league_name,
                fetched_at=now,
                events=levents,
            ))

    except Exception as e:
        print(f"[Pinnacle] Error fetching {sport_key}: {e}")
    finally:
        if close_client:
            await client.aclose()

    return snapshots


async def fetch_league(league_key: str, client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    """Fetch odds for a specific league from Pinnacle."""
    close_client = False
    if client is None:
        client = httpx.AsyncClient(headers=HEADERS, timeout=30.0)
        close_client = True

    snapshots = []
    league_id = LEAGUE_IDS.get(league_key)
    if not league_id:
        return []

    try:
        matchups_resp = await client.get(f"{BASE_URL}/leagues/{league_id}/matchups")
        matchups_resp.raise_for_status()
        matchups = matchups_resp.json()

        markets_resp = await client.get(f"{BASE_URL}/leagues/{league_id}/markets/straight")
        markets_resp.raise_for_status()
        markets = markets_resp.json()

        # Determine sport name from league
        sport_name = "Unknown"
        if matchups:
            league_info = matchups[0].get("league", {}) or {}
            sport_info = league_info.get("sport", {}) or {}
            sport_name = sport_info.get("name", "Unknown")

        events = _parse_matchups_and_markets(matchups, markets, sport_name)
        now = datetime.now(timezone.utc)

        if events:
            snapshots.append(SportsbookSnapshot(
                sportsbook=SPORTSBOOK_NAME,
                sport=sport_name,
                league=league_key,
                fetched_at=now,
                events=events,
            ))

    except Exception as e:
        print(f"[Pinnacle] Error fetching league {league_key}: {e}")
    finally:
        if close_client:
            await client.aclose()

    return snapshots


async def fetch_all() -> List[SportsbookSnapshot]:
    """Fetch odds for all supported sports from Pinnacle."""
    all_snapshots = []
    async with httpx.AsyncClient(headers=HEADERS, timeout=30.0) as client:
        for sport_key in SPORT_IDS.keys():
            snapshots = await fetch_sport(sport_key, client)
            all_snapshots.extend(snapshots)
    return all_snapshots


async def fetch_nfl(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_league("NFL", client)

async def fetch_nba(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_league("NBA", client)

async def fetch_mlb(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_league("MLB", client)

async def fetch_nhl(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_league("NHL", client)