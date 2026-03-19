"""
Kambi Multi-Operator scraper.
The Kambi platform powers 20+ sportsbooks. Different operators may have
slightly different odds due to margin adjustments.

Accessible operators:
- ub (Unibet) - primary
- paf (PAF) - Finnish
- svenskaspel (Svenska Spel) - Swedish state
- atg (ATG) - Swedish
- ubuk (Unibet UK)
- ubse (Unibet SE)
- ubnl (Unibet NL)

This module provides a function to fetch from a specific Kambi operator.
"""
import httpx
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from .models import SportsbookSnapshot, Event, Market, Outcome, MarketType

BASE_URL = "https://eu-offering-api.kambicdn.com/offering/v2018"

# Operator configs: (code, display_name, market_param)
KAMBI_OPERATORS = {
    "888sport": ("888", "888sport", "GB"),       # Currently returning 400
    "leovegas": ("leovegas", "LeoVegas", "GB"),  # Currently returning 400
    "betsson": ("betsson", "Betsson", "SE"),      # Currently returning 429
    "paf": ("paf", "PAF", "FI"),
    "svenskaspel": ("svenskaspel", "Svenska Spel", "SE"),
    "atg": ("atg", "ATG", "SE"),
    "unibet_uk": ("ubuk", "Unibet UK", "GB"),
    "unibet_se": ("ubse", "Unibet SE", "SE"),
    "unibet_nl": ("ubnl", "Unibet NL", "NL"),
}

# Only operators confirmed working
WORKING_OPERATORS = ["paf", "svenskaspel", "atg", "unibet_uk", "unibet_se", "unibet_nl"]

SPORT_PATHS = {
    "nba": "basketball",
    "ncaab": "basketball",
    "wnba": "basketball",
    "nfl": "american_football",
    "ncaaf": "american_football",
    "mlb": "baseball",
    "nhl": "ice_hockey",
    "soccer": "football",
    "tennis": "tennis",
    "golf": "golf",
    "mma": "ufc_mma",
    "boxing": "boxing",
    "cricket": "cricket",
    "rugby_union": "rugby_union",
    "rugby_league": "rugby_league",
    "darts": "darts",
    "table_tennis": "table_tennis",
    "handball": "handball",
    "volleyball": "volleyball",
    "cycling": "cycling",
    "snooker": "snooker",
    "motorsport": "motorsport",
    "afl": "australian_rules",
}


def _parse_line(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val) / 1000.0
    except:
        return None


def _decimal_to_american(dec: float) -> Optional[int]:
    if dec <= 1.0:
        return None
    if dec >= 2.0:
        return int(round((dec - 1) * 100))
    return int(round(-100 / (dec - 1)))


def _classify_market(criterion_label: str) -> Tuple[MarketType, bool]:
    label = criterion_label.lower()
    skip_keywords = ["future", "outright", "season", "mvp", "award", "championship"]
    if any(kw in label for kw in skip_keywords):
        return MarketType.FUTURES, True
    if "match" in label or "moneyline" in label or "1x2" in label or "full time" in label:
        return MarketType.MONEYLINE, False
    if "handicap" in label or "spread" in label:
        return MarketType.SPREAD, False
    if "total" in label or "over/under" in label:
        return MarketType.TOTAL, False
    if "player" in label or "scorer" in label:
        return MarketType.PLAYER_PROP, False
    return MarketType.OTHER, False


async def fetch_operator(operator_key: str, sport: str) -> List[SportsbookSnapshot]:
    """Fetch odds from a specific Kambi operator."""
    if operator_key not in KAMBI_OPERATORS:
        return []
    
    code, display_name, market_param = KAMBI_OPERATORS[operator_key]
    sport_path = SPORT_PATHS.get(sport)
    if not sport_path:
        return []

    url = f"{BASE_URL}/{code}/listView/{sport_path}/all/all/all/matches.json?lang=en_US&market={market_param}"

    async with httpx.AsyncClient(timeout=20) as client:
        try:
            r = await client.get(url)
            if r.status_code != 200:
                return []
            data = r.json()
        except Exception as e:
            print(f"[Kambi-{display_name}] Error: {e}")
            return []

    raw_events = data.get("events", [])
    events = []

    for raw in raw_events:
        ev = raw.get("event", {})
        if not ev:
            continue

        event_id = str(ev.get("id", ""))
        name = ev.get("name", "")
        home = ev.get("homeName", "")
        away = ev.get("awayName", "")
        group = ev.get("group", "")
        sport_name = ev.get("sport", sport)

        start_str = ev.get("start", "")
        start_time = None
        if start_str:
            try:
                start_time = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            except:
                pass

        is_live = ev.get("state", "") == "STARTED"

        markets = []
        for bo in raw.get("betOffers", []):
            criterion = bo.get("criterion", {})
            criterion_label = criterion.get("label", "")
            market_type, skip = _classify_market(criterion_label)
            if skip:
                continue

            outcomes = []
            for oc in bo.get("outcomes", []):
                oc_label = oc.get("label", oc.get("englishLabel", ""))
                oc_odds = oc.get("odds")
                if not oc_odds:
                    continue

                decimal_odds = round(oc_odds / 1000.0, 4)
                american = _decimal_to_american(decimal_odds)
                line = _parse_line(oc.get("line"))

                outcomes.append(Outcome(
                    name=oc_label,
                    price_american=american,
                    price_decimal=decimal_odds,
                    point=line,
                ))

            if outcomes:
                markets.append(Market(
                    market_type=market_type,
                    name=criterion_label,
                    outcomes=outcomes,
                ))

        if markets:
            events.append(Event(
                event_id=event_id,
                sport=sport_name,
                league=group,
                home_team=home,
                away_team=away,
                description=f"{away} @ {home}" if away else name,
                start_time=start_time,
                is_live=is_live,
                markets=markets,
            ))

    snapshots = []
    if events:
        snapshots.append(SportsbookSnapshot(
            sportsbook=display_name,
            sport=sport,
            league=sport.upper(),
            events=events,
            fetched_at=datetime.now(timezone.utc),
        ))

    return snapshots


async def fetch_all_operators(sport: str) -> List[SportsbookSnapshot]:
    """Fetch from all working Kambi operators concurrently."""
    import asyncio
    tasks = [fetch_operator(op, sport) for op in WORKING_OPERATORS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    snapshots = []
    for result in results:
        if isinstance(result, list):
            snapshots.extend(result)
    
    return snapshots