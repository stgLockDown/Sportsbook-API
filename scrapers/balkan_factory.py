"""
Balkan Sportsbook Factory
Creates scrapers for MaxBet-style Balkan sportsbooks that share the same REST API format.

Confirmed working operators:
  - maxbet.rs (already has dedicated scraper)
  - soccerbet.rs (12 sports)
  - merkurxtip.rs (12 sports)
  - betole.rs (soccer confirmed)

API format: https://{domain}/restapi/offer/sr/sport/{code}/mob?annex=0&desession=true
Response: {"esMatches": [{id, home, away, odds: {1: home, 2: draw, 3: away, ...}, params: {hd2, overUnder}}]}
"""

import httpx
import json
from datetime import datetime, timezone
from typing import List, Optional
from .models import SportsbookSnapshot, Event, Market, Outcome, MarketType

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

# All confirmed Balkan operators
BALKAN_OPERATORS = {
    "soccerbet": {
        "name": "SoccerBet RS",
        "base_url": "https://www.soccerbet.rs/restapi/offer/sr/sport",
    },
    "merkur": {
        "name": "Merkur RS",
        "base_url": "https://www.merkurxtip.rs/restapi/offer/sr/sport",
    },
    "betole": {
        "name": "BetOle RS",
        "base_url": "https://www.betole.rs/restapi/offer/sr/sport",
    },
}

# Sport code mappings (same as MaxBet)
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
    if not dec or dec <= 1.0:
        return None
    if dec >= 2.0:
        return int(round((dec - 1) * 100))
    return int(round(-100 / (dec - 1)))


def _extract_odds(match: dict) -> dict:
    """Extract odds from either 'odds' dict or 'betMap' dict."""
    # MaxBet/Merkur style: odds = {"1": 1.5, "2": 3.2, ...}
    odds = match.get("odds", {})
    if odds:
        return odds
    
    # SoccerBet style: betMap = {"1": {"NULL": {"ov": 1.5, ...}}, ...}
    betmap = match.get("betMap", {})
    if betmap:
        extracted = {}
        for tid, entries in betmap.items():
            for key, val in entries.items():
                ov = val.get("ov")
                if ov and isinstance(ov, (int, float)) and ov > 0:
                    extracted[tid] = ov
        return extracted
    
    return {}


def _parse_match(match: dict, sport_info: dict) -> Optional[Event]:
    home = match.get("home", "")
    away = match.get("away", "")
    if not home or not away:
        return None

    event_id = str(match.get("id", ""))
    is_live = match.get("live", False)
    
    start_time = None
    ko = match.get("kickOffTime")
    if ko:
        try:
            start_time = datetime.fromtimestamp(ko / 1000, tz=timezone.utc)
        except:
            pass

    odds = _extract_odds(match)
    params = match.get("params", {})
    league_name = match.get("leagueName", sport_info["league"])
    three_way = sport_info.get("three_way", False)
    
    markets = []

    # Moneyline
    home_odds = odds.get("1")
    if three_way:
        draw_odds = odds.get("2")
        away_odds = odds.get("3")
    else:
        draw_odds = None
        away_odds = odds.get("2") if odds.get("2") else odds.get("3")

    ml_outcomes = []
    if home_odds and home_odds > 1.0:
        ml_outcomes.append(Outcome(name=home, price_american=_decimal_to_american(home_odds), price_decimal=round(home_odds, 3)))
    if draw_odds and draw_odds > 1.0 and three_way:
        ml_outcomes.append(Outcome(name="Draw", price_american=_decimal_to_american(draw_odds), price_decimal=round(draw_odds, 3)))
    if away_odds and away_odds > 1.0:
        ml_outcomes.append(Outcome(name=away, price_american=_decimal_to_american(away_odds), price_decimal=round(away_odds, 3)))
    
    if len(ml_outcomes) >= 2:
        markets.append(Market(market_type=MarketType.MONEYLINE, name="Moneyline", outcomes=ml_outcomes))

    # Spread/Handicap
    hd_line = params.get("hd2")
    hc_home = odds.get("800")
    hc_away = odds.get("801")
    if hd_line is not None and hc_home and hc_away:
        try:
            line_val = float(hd_line)
            spread_outcomes = []
            if hc_home > 0:
                spread_outcomes.append(Outcome(name=home, price_american=_decimal_to_american(hc_home), price_decimal=round(hc_home, 3), point=line_val))
            if hc_away > 0:
                spread_outcomes.append(Outcome(name=away, price_american=_decimal_to_american(hc_away), price_decimal=round(hc_away, 3), point=-line_val))
            if len(spread_outcomes) == 2:
                markets.append(Market(market_type=MarketType.SPREAD, name="Spread", outcomes=spread_outcomes))
        except (ValueError, TypeError):
            pass

    # Total (Over/Under)
    over_odds = odds.get("606")
    under_odds = odds.get("607")
    if over_odds and under_odds and over_odds > 1.0 and under_odds > 1.0:
        total_line = None
        ou_param = params.get("overUnder")
        if ou_param:
            try:
                total_line = float(ou_param)
            except:
                pass
        if total_line is None and sport_info["sport"] == "Soccer":
            total_line = 2.5

        total_outcomes = [
            Outcome(name="Over", price_american=_decimal_to_american(over_odds), price_decimal=round(over_odds, 3), point=total_line),
            Outcome(name="Under", price_american=_decimal_to_american(under_odds), price_decimal=round(under_odds, 3), point=total_line),
        ]
        markets.append(Market(market_type=MarketType.TOTAL, name="Total", outcomes=total_outcomes))

    return Event(
        event_id=event_id, sport=sport_info["sport"], league=league_name,
        home_team=home, away_team=away, description=f"{away} @ {home}",
        start_time=start_time, is_live=is_live, markets=markets,
    )


async def fetch_operator_sport(operator_id: str, sport_key: str) -> List[SportsbookSnapshot]:
    """
    Fetch odds from a specific Balkan operator for a given sport.
    """
    op_info = BALKAN_OPERATORS.get(operator_id)
    if not op_info:
        return []
    
    mapping = SPORT_MAP.get(sport_key)
    if not mapping:
        return []

    base_url = op_info["base_url"]
    display_name = op_info["name"]
    code = mapping["code"]
    league_filter = mapping.get("league")
    sport_label = mapping["sport"]
    
    url = f"{base_url}/{code}/mob?annex=0&desession=true"

    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        try:
            resp = await client.get(url, headers=HEADERS)
            if resp.status_code != 200:
                return []
            text = resp.text
            if not (text.strip().startswith('{') or text.strip().startswith('[')):
                return []
            data = json.loads(text)
        except Exception as e:
            print(f"[{display_name}] Error fetching {sport_key}: {e}")
            return []

    raw_matches = data.get("esMatches", [])
    if not raw_matches:
        return []

    events = []
    for match in raw_matches:
        if league_filter and league_filter not in ("Soccer", "Tennis", "Handball", 
            "Volleyball", "MMA", "Esports", "Darts", "Table Tennis", "Rugby Union",
            "Cricket", "Boxing", "Snooker", "Golf"):
            league_name = match.get("leagueName", "")
            if league_filter.upper() not in league_name.upper():
                continue

        event = _parse_match(match, mapping)
        if event and event.markets:
            events.append(event)
    
    events = events[:50]

    if not events:
        return []

    return [SportsbookSnapshot(
        sportsbook=display_name,
        sport=sport_label,
        league=league_filter or sport_label,
        fetched_at=datetime.now(timezone.utc),
        events=events,
    )]