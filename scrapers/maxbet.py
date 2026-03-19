"""
MaxBet Scraper (Serbian Sportsbook)
MaxBet is a major Serbian/Balkan sportsbook with a clean REST API.
Returns massive amounts of data — 900+ soccer events, 70+ basketball, 90+ tennis.

API: https://maxbet.rs/restapi/offer/sr/sport/{code}/mob
Odds are in decimal format. Standard IDs:
  Soccer: 1=Home, 2=Draw, 3=Away (1X2), 606=Over2.5, 607=Under2.5, hd2=handicap line, 800/801=HC
  Basketball: 1=Home, 2=Away (ML), params have overUnder and handicap lines
  Tennis: 1=Home, 3=Away (2-way ML)
"""

import httpx
from datetime import datetime, timezone
from typing import List, Optional
from .models import SportsbookSnapshot, Event, Market, Outcome, MarketType

BASE_URL = "https://maxbet.rs/restapi/offer/sr/sport"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

# Sport code mappings: our key -> (MaxBet code, sport label, league label, is_3way)
SPORT_MAP = {
    "soccer": {"code": "S", "sport": "Soccer", "league": "Soccer", "three_way": True},
    "soccer_epl": {"code": "S", "sport": "Soccer", "league": "Premier League", "three_way": True},
    "basketball_nba": {"code": "B", "sport": "Basketball", "league": "NBA", "three_way": False},
    "basketball_ncaab": {"code": "B", "sport": "Basketball", "league": "NCAA", "three_way": False},
    "tennis": {"code": "T", "sport": "Tennis", "league": "Tennis", "three_way": False},
    "ice_hockey_nhl": {"code": "H", "sport": "Hockey", "league": "NHL", "three_way": True},
    "baseball_mlb": {"code": "BB", "sport": "Baseball", "league": "MLB", "three_way": False},
    "handball": {"code": "HB", "sport": "Handball", "league": "Handball", "three_way": True},
    "volleyball": {"code": "V", "sport": "Volleyball", "league": "Volleyball", "three_way": False},
    "mma": {"code": "MMA", "sport": "MMA", "league": "MMA", "three_way": False},
    "mma_ufc": {"code": "MMA", "sport": "MMA", "league": "UFC", "three_way": False},
    "esports": {"code": "ES", "sport": "Esports", "league": "Esports", "three_way": False},
    "darts": {"code": "D", "sport": "Darts", "league": "Darts", "three_way": False},
    "table_tennis": {"code": "TT", "sport": "Table Tennis", "league": "Table Tennis", "three_way": False},
    "rugby_union": {"code": "R", "sport": "Rugby", "league": "Rugby Union", "three_way": True},
    "cricket": {"code": "CR", "sport": "Cricket", "league": "Cricket", "three_way": False},
    "football_nfl": {"code": "AF", "sport": "Football", "league": "NFL", "three_way": False},
    "football_ncaaf": {"code": "AF", "sport": "Football", "league": "NCAAF", "three_way": False},
    "boxing": {"code": "BO", "sport": "Boxing", "league": "Boxing", "three_way": False},
    "snooker": {"code": "SN", "sport": "Snooker", "league": "Snooker", "three_way": False},
    "golf": {"code": "G", "sport": "Golf", "league": "Golf", "three_way": False},
}


def _decimal_to_american(dec: float) -> Optional[int]:
    """Convert decimal odds to American format."""
    if not dec or dec <= 1.0:
        return None
    if dec >= 2.0:
        return int(round((dec - 1) * 100))
    return int(round(-100 / (dec - 1)))


def _parse_match(match: dict, sport_info: dict) -> Optional[Event]:
    """Parse a single match into an Event."""
    home = match.get("home", "")
    away = match.get("away", "")
    if not home or not away:
        return None

    event_id = str(match.get("id", ""))
    is_live = match.get("live", False)
    
    # Parse kickoff time (milliseconds timestamp)
    start_time = None
    ko = match.get("kickOffTime")
    if ko:
        try:
            start_time = datetime.fromtimestamp(ko / 1000, tz=timezone.utc)
        except:
            pass

    odds = match.get("odds", {})
    params = match.get("params", {})
    league_name = match.get("leagueName", sport_info["league"])
    
    markets = []
    three_way = sport_info.get("three_way", False)

    # ── Moneyline ──
    home_odds = odds.get("1")
    away_odds = odds.get("3") if not three_way else odds.get("3")
    draw_odds = odds.get("2") if three_way else None
    
    # For 2-way sports, away is ID 2 if no draw
    if not three_way:
        away_odds = odds.get("2") if odds.get("2") else odds.get("3")
    
    ml_outcomes = []
    if home_odds and home_odds > 1.0:
        ml_outcomes.append(Outcome(
            name=home, price_american=_decimal_to_american(home_odds), price_decimal=round(home_odds, 3)
        ))
    if draw_odds and draw_odds > 1.0 and three_way:
        ml_outcomes.append(Outcome(
            name="Draw", price_american=_decimal_to_american(draw_odds), price_decimal=round(draw_odds, 3)
        ))
    if away_odds and away_odds > 1.0:
        ml_outcomes.append(Outcome(
            name=away, price_american=_decimal_to_american(away_odds), price_decimal=round(away_odds, 3)
        ))
    
    if len(ml_outcomes) >= 2:
        markets.append(Market(market_type=MarketType.MONEYLINE, name="Moneyline", outcomes=ml_outcomes))

    # ── Spread/Handicap ──
    hd_line = params.get("hd2")
    hc_home = odds.get("800")
    hc_away = odds.get("801")
    if hd_line is not None and hc_home and hc_away:
        try:
            line_val = float(hd_line)
            spread_outcomes = []
            if hc_home > 0:
                spread_outcomes.append(Outcome(
                    name=home, price_american=_decimal_to_american(hc_home),
                    price_decimal=round(hc_home, 3), point=line_val
                ))
            if hc_away > 0:
                spread_outcomes.append(Outcome(
                    name=away, price_american=_decimal_to_american(hc_away),
                    price_decimal=round(hc_away, 3), point=-line_val
                ))
            if len(spread_outcomes) == 2:
                markets.append(Market(market_type=MarketType.SPREAD, name="Spread", outcomes=spread_outcomes))
        except (ValueError, TypeError):
            pass

    # ── Total (Over/Under) ──
    # For soccer: 606=Over 2.5, 607=Under 2.5
    # For basketball: params.overUnder has the line
    over_odds = odds.get("606")
    under_odds = odds.get("607")
    
    if over_odds and under_odds and over_odds > 1.0 and under_odds > 1.0:
        # Determine total line from params or default
        total_line = None
        ou_param = params.get("overUnder")
        if ou_param:
            try:
                total_line = float(ou_param)
            except:
                pass
        if total_line is None:
            # Default for soccer is 2.5
            if sport_info["sport"] == "Soccer":
                total_line = 2.5

        total_outcomes = [
            Outcome(name="Over", price_american=_decimal_to_american(over_odds),
                    price_decimal=round(over_odds, 3), point=total_line),
            Outcome(name="Under", price_american=_decimal_to_american(under_odds),
                    price_decimal=round(under_odds, 3), point=total_line),
        ]
        markets.append(Market(market_type=MarketType.TOTAL, name="Total", outcomes=total_outcomes))

    return Event(
        event_id=event_id,
        sport=sport_info["sport"],
        league=league_name,
        home_team=home,
        away_team=away,
        description=f"{away} @ {home}",
        start_time=start_time,
        is_live=is_live,
        markets=markets,
    )


async def fetch_sport(sport_key: str) -> List[SportsbookSnapshot]:
    """
    Fetch odds from MaxBet for a given sport.
    """
    mapping = SPORT_MAP.get(sport_key)
    if not mapping:
        return []

    code = mapping["code"]
    league_filter = mapping.get("league")
    sport_label = mapping["sport"]
    
    url = f"{BASE_URL}/{code}/mob?annex=0&desession=true"

    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        try:
            resp = await client.get(url, headers=HEADERS)
            if resp.status_code != 200:
                return []
            
            # MaxBet returns JSON with text/html content-type
            text = resp.text
            if not (text.strip().startswith('{') or text.strip().startswith('[')):
                return []
            
            import json
            data = json.loads(text)
        except Exception as e:
            print(f"[MaxBet] Error fetching {sport_key}: {e}")
            return []

    raw_matches = data.get("esMatches", [])
    if not raw_matches:
        return []

    # Filter by league if needed
    events = []
    for match in raw_matches:
        # League filtering for specific leagues
        if league_filter and league_filter not in ("Soccer", "Tennis", "Handball", 
            "Volleyball", "MMA", "Esports", "Darts", "Table Tennis", "Rugby Union",
            "Cricket", "Boxing", "Snooker", "Golf"):
            league_name = match.get("leagueName", "")
            if league_filter.upper() not in league_name.upper():
                continue

        event = _parse_match(match, mapping)
        if event and event.markets:
            events.append(event)
    
    # Limit to 50 events for performance
    events = events[:50]

    if not events:
        return []

    return [SportsbookSnapshot(
        sportsbook="MaxBet",
        sport=sport_label,
        league=league_filter or sport_label,
        fetched_at=datetime.now(timezone.utc),
        events=events,
    )]