"""
Kambi Factory - Creates scrapers for multiple Kambi CDN operators.
All Kambi operators use the same API pattern, just with different operator keys.

Confirmed working operators:
  - coolbet (existing)
  - comeon (existing)
  - ubbe (Unibet Belgium)
  - ubro (Unibet Romania)
  - ubde (Unibet Germany)
  - ubdk (Unibet Denmark)
  - ubca (Unibet Canada Ontario)
  - 888it (888sport Italy)
  - bingoalbe (Bingoal Belgium)
  - betcitynl (BetCity Netherlands)
"""

import asyncio
import httpx
from datetime import datetime, timezone
from typing import List, Optional
from .models import SportsbookSnapshot, Event, Market, Outcome, MarketType

KAMBI_BASE = "https://eu-offering-api.kambicdn.com/offering/v2018"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

# All Kambi operators we've confirmed working
KAMBI_OPERATORS = {
    "unibet_be": {"key": "ubbe", "name": "Unibet BE", "market": "BE"},
    "unibet_ro": {"key": "ubro", "name": "Unibet RO", "market": "RO"},
    "unibet_de": {"key": "ubde", "name": "Unibet DE", "market": "DE"},
    "unibet_dk": {"key": "ubdk", "name": "Unibet DK", "market": "DK"},
    "unibet_ca": {"key": "ubca", "name": "Unibet CA", "market": "CA"},
    "888sport_it": {"key": "888it", "name": "888sport IT", "market": "IT"},
    "bingoal": {"key": "bingoalbe", "name": "Bingoal", "market": "BE"},
    "betcity": {"key": "betcitynl", "name": "BetCity NL", "market": "NL"},
}

# Sport path mappings (same as coolbet/comeon)
SPORT_MAP = {
    "basketball_nba": {"path": "basketball", "league_filter": "NBA"},
    "basketball_ncaab": {"path": "basketball", "league_filter": "NCAA"},
    "football_nfl": {"path": "american_football", "league_filter": "NFL"},
    "football_ncaaf": {"path": "american_football", "league_filter": "NCAA"},
    "baseball_mlb": {"path": "baseball", "league_filter": "MLB"},
    "ice_hockey_nhl": {"path": "ice_hockey", "league_filter": "NHL"},
    "soccer": {"path": "football", "league_filter": None},
    "soccer_epl": {"path": "football", "league_filter": "Premier League"},
    "tennis": {"path": "tennis", "league_filter": None},
    "mma_ufc": {"path": "mma", "league_filter": "UFC"},
    "mma": {"path": "mma", "league_filter": None},
    "boxing": {"path": "boxing", "league_filter": None},
    "golf": {"path": "golf", "league_filter": None},
    "cricket": {"path": "cricket", "league_filter": None},
    "rugby_union": {"path": "rugby_union", "league_filter": None},
    "rugby_league": {"path": "rugby_league", "league_filter": None},
    "darts": {"path": "darts", "league_filter": None},
    "table_tennis": {"path": "table_tennis", "league_filter": None},
    "volleyball": {"path": "volleyball", "league_filter": None},
    "handball": {"path": "handball", "league_filter": None},
    "snooker": {"path": "snooker", "league_filter": None},
    "cycling": {"path": "cycling", "league_filter": None},
    "esports": {"path": "esports", "league_filter": None},
    "aussie_rules": {"path": "aussie_rules", "league_filter": None},
    "motor_sports": {"path": "motor_sport", "league_filter": None},
}


def _kambi_odds_to_decimal(odds_value: int) -> float:
    return round(odds_value / 1000, 3) if odds_value else 0.0


def _decimal_to_american(dec: float) -> Optional[int]:
    if dec <= 1.0:
        return None
    if dec >= 2.0:
        return int(round((dec - 1) * 100))
    return int(round(-100 / (dec - 1)))


def _kambi_line(value: int) -> float:
    return round(value / 1000, 1) if value else 0.0


def _parse_moneyline(outcomes: list) -> Optional[Market]:
    parsed = []
    for oc in outcomes:
        odds_raw = oc.get("odds")
        if not odds_raw:
            continue
        dec = _kambi_odds_to_decimal(odds_raw)
        american = _decimal_to_american(dec)
        parsed.append(Outcome(
            name=oc.get("label", oc.get("englishLabel", "?")),
            price_american=american, price_decimal=dec,
        ))
    if len(parsed) >= 2:
        return Market(market_type=MarketType.MONEYLINE, name="Moneyline", outcomes=parsed)
    return None


def _parse_spread(outcomes: list) -> Optional[Market]:
    parsed = []
    for oc in outcomes:
        odds_raw = oc.get("odds")
        line_raw = oc.get("line")
        if not odds_raw:
            continue
        dec = _kambi_odds_to_decimal(odds_raw)
        american = _decimal_to_american(dec)
        point = _kambi_line(line_raw) if line_raw else None
        parsed.append(Outcome(
            name=oc.get("label", oc.get("englishLabel", "?")),
            price_american=american, price_decimal=dec, point=point,
        ))
    if len(parsed) >= 2:
        return Market(market_type=MarketType.SPREAD, name="Spread", outcomes=parsed)
    return None


def _parse_total(outcomes: list) -> Optional[Market]:
    parsed = []
    for oc in outcomes:
        odds_raw = oc.get("odds")
        line_raw = oc.get("line")
        if not odds_raw:
            continue
        dec = _kambi_odds_to_decimal(odds_raw)
        american = _decimal_to_american(dec)
        point = _kambi_line(line_raw) if line_raw else None
        label = oc.get("label", oc.get("englishLabel", "?"))
        oc_type = oc.get("type", "")
        if oc_type == "OT_OVER" or "over" in label.lower():
            label = "Over"
        elif oc_type == "OT_UNDER" or "under" in label.lower():
            label = "Under"
        parsed.append(Outcome(
            name=label, price_american=american, price_decimal=dec, point=point,
        ))
    if len(parsed) >= 2:
        return Market(market_type=MarketType.TOTAL, name="Total", outcomes=parsed)
    return None


def _parse_event(ev_data: dict, sport: str, league: str) -> Optional[Event]:
    evt = ev_data.get("event", {})
    if not evt:
        return None
    home = evt.get("homeName", "")
    away = evt.get("awayName", "")
    if not home or not away:
        return None

    event_id = str(evt.get("id", ""))
    start_str = evt.get("start")
    start_time = None
    if start_str:
        try:
            start_time = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        except:
            pass
    is_live = evt.get("state", "") == "STARTED"

    markets = []
    for offer in ev_data.get("betOffers", []):
        crit = offer.get("criterion", {})
        label = crit.get("label", "")
        outcomes = offer.get("outcomes", [])
        if not outcomes:
            continue

        if label in ["Full Time", "Match", "Moneyline", "To Win Match", "Fight Winner",
                      "Winner", "Match Winner", "1X2", "Money Line"]:
            mkt = _parse_moneyline(outcomes)
            if mkt:
                markets.append(mkt)
        elif "Handicap" in label or "Spread" in label or "Point Spread" in label:
            mkt = _parse_spread(outcomes)
            if mkt:
                markets.append(mkt)
        elif label in ["Total Goals", "Total Points", "Total", "Total Runs",
                        "Total Games", "Total Rounds"] or "Over/Under" in label:
            mkt = _parse_total(outcomes)
            if mkt:
                markets.append(mkt)
        elif "Full Time" in label or "1X2" in label or "Match" == label:
            mkt = _parse_moneyline(outcomes)
            if mkt:
                markets.append(mkt)
        elif "Total" in label and ("Goals" in label or "Points" in label or "Over" in label.lower()):
            mkt = _parse_total(outcomes)
            if mkt:
                markets.append(mkt)

    return Event(
        event_id=event_id, sport=sport, league=league,
        home_team=home, away_team=away, description=f"{away} @ {home}",
        start_time=start_time, is_live=is_live, markets=markets,
    )


def _parse_betoffer_detail(detail_data: dict, base_event: Event) -> Event:
    markets = []
    for offer in detail_data.get("betOffers", []):
        crit = offer.get("criterion", {})
        label = crit.get("label", "").strip()
        outcomes = offer.get("outcomes", [])
        if not outcomes:
            continue

        if label in ["Full Time", "Match", "Moneyline", "To Win Match", "Fight Winner",
                      "Winner", "Match Winner", "1X2", "Money Line"]:
            mkt = _parse_moneyline(outcomes)
            if mkt:
                markets.append(mkt)
        elif "Handicap" in label or "Spread" in label or "Point Spread" in label:
            mkt = _parse_spread(outcomes)
            if mkt:
                markets.append(mkt)
        elif label in ["Total Goals", "Total Points", "Total", "Total Runs",
                        "Total Games", "Total Rounds"] or "Over/Under" in label:
            mkt = _parse_total(outcomes)
            if mkt:
                markets.append(mkt)

    if markets:
        base_event.markets = markets
    return base_event


async def _fetch_event_detail(client: httpx.AsyncClient, operator_key: str, 
                               event_id: str, market: str) -> Optional[dict]:
    url = f"{KAMBI_BASE}/{operator_key}/betoffer/event/{event_id}.json?lang=en_GB&market={market}"
    try:
        resp = await client.get(url, headers=HEADERS)
        if resp.status_code == 200:
            return resp.json()
    except:
        pass
    return None


async def fetch_operator_sport(operator_id: str, sport_key: str) -> List[SportsbookSnapshot]:
    """
    Fetch odds from a specific Kambi operator for a given sport.
    
    Args:
        operator_id: Key from KAMBI_OPERATORS (e.g., 'unibet_be')
        sport_key: Key from SPORT_MAP (e.g., 'soccer', 'basketball_nba')
    """
    op_info = KAMBI_OPERATORS.get(operator_id)
    if not op_info:
        return []
    
    mapping = SPORT_MAP.get(sport_key)
    if not mapping:
        return []

    operator_key = op_info["key"]
    display_name = op_info["name"]
    market = op_info["market"]
    kambi_path = mapping["path"]
    league_filter = mapping.get("league_filter")

    list_url = f"{KAMBI_BASE}/{operator_key}/listView/{kambi_path}.json?lang=en_GB&market={market}&useCombined=true"

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        try:
            resp = await client.get(list_url, headers=HEADERS)
            if resp.status_code != 200:
                return []
            data = resp.json()
        except Exception as e:
            print(f"[{display_name}] Error fetching {sport_key}: {e}")
            return []

        raw_events = data.get("events", [])
        if not raw_events:
            return []

        sport_label = kambi_path.replace("_", " ").title()
        if kambi_path == "american_football":
            sport_label = "Football"
        elif kambi_path == "ice_hockey":
            sport_label = "Hockey"
        elif kambi_path == "football":
            sport_label = "Soccer"
        league_label = league_filter or sport_label

        events = []
        event_ids_for_detail = []

        for ev in raw_events:
            evt = ev.get("event", {})
            if league_filter:
                event_path = evt.get("path", [])
                group = evt.get("group", "")
                event_name = evt.get("name", "")
                path_str = "/".join(
                    p.get("englishName", "") if isinstance(p, dict) else str(p)
                    for p in event_path
                ) if event_path else ""
                if not any(league_filter.lower() in s.lower() 
                          for s in [path_str, group, event_name, str(event_path)]):
                    continue

            parsed = _parse_event(ev, sport_label, league_label)
            if parsed:
                events.append(parsed)
                event_ids_for_detail.append(parsed.event_id)

        # Fetch detail for up to 20 events
        if event_ids_for_detail:
            detail_tasks = [
                _fetch_event_detail(client, operator_key, eid, market)
                for eid in event_ids_for_detail[:20]
            ]
            detail_results = await asyncio.gather(*detail_tasks, return_exceptions=True)
            for i, result in enumerate(detail_results):
                if isinstance(result, dict) and i < len(events):
                    events[i] = _parse_betoffer_detail(result, events[i])

    if not events:
        return []

    return [SportsbookSnapshot(
        sportsbook=display_name,
        sport=sport_label,
        league=league_label,
        fetched_at=datetime.now(timezone.utc),
        events=events,
    )]