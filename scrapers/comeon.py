"""
ComeOn Scraper (Kambi CDN)
ComeOn is an international sportsbook powered by Kambi.
Uses the same Kambi CDN as Coolbet/Unibet but with 'comeon' operator key.

Confirmed working across 17 sports with strong coverage in:
  - Football/Soccer: 141+ events
  - Esports: 66+ events
  - Plus seasonal coverage for NBA, NFL, MLB, NHL, Tennis, etc.

Approach:
  1. listView/{sport}.json -> event list with basic odds
  2. betoffer/event/{id}.json -> full market detail (ML, spread, total)
"""

import asyncio
import httpx
from datetime import datetime, timezone
from typing import List, Optional
from .models import SportsbookSnapshot, Event, Market, Outcome, MarketType

KAMBI_BASE = "https://eu-offering-api.kambicdn.com/offering/v2018/comeon"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

# Sport path mappings for ComeOn Kambi
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
    "mma": {"path": "mma", "league_filter": None},
}


def _kambi_odds_to_decimal(odds_value: int) -> float:
    """Kambi returns odds * 1000 (e.g., 1860 = 1.86)."""
    return round(odds_value / 1000, 3) if odds_value else 0.0


def _decimal_to_american(dec: float) -> Optional[int]:
    """Convert decimal odds to American format."""
    if dec <= 1.0:
        return None
    if dec >= 2.0:
        return int(round((dec - 1) * 100))
    return int(round(-100 / (dec - 1)))


def _kambi_line(value: int) -> float:
    """Kambi returns lines * 1000 (e.g., 5500 = 5.5)."""
    return round(value / 1000, 1) if value else 0.0


def _parse_event_from_list(ev_data: dict, sport: str, league: str) -> Optional[Event]:
    """Parse an event from the listView response."""
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

    # Parse basic odds from listView betOffers
    markets = []
    for offer in ev_data.get("betOffers", []):
        crit = offer.get("criterion", {})
        label = crit.get("label", "")
        outcomes = offer.get("outcomes", [])

        if "Full Time" in label or "1X2" in label or "Match" == label:
            mkt = _parse_moneyline(outcomes)
            if mkt:
                markets.append(mkt)
        elif "Handicap" in label:
            mkt = _parse_spread(outcomes)
            if mkt:
                markets.append(mkt)
        elif "Total" in label and "Goals" in label or "Points" in label or "Over" in label.lower():
            mkt = _parse_total(outcomes)
            if mkt:
                markets.append(mkt)

    return Event(
        event_id=event_id,
        sport=sport,
        league=league,
        home_team=home,
        away_team=away,
        description=f"{away} @ {home}",
        start_time=start_time,
        is_live=is_live,
        markets=markets,
    )


def _parse_betoffer_detail(detail_data: dict, base_event: Event) -> Event:
    """Parse full market detail from betoffer/event endpoint."""
    markets = []
    for offer in detail_data.get("betOffers", []):
        crit = offer.get("criterion", {})
        label = crit.get("label", "").strip()
        outcomes = offer.get("outcomes", [])

        if not outcomes:
            continue

        # Moneyline / Match Winner
        if label in ["Full Time", "Match", "Moneyline", "To Win Match", "Fight Winner",
                      "Winner", "Match Winner", "1X2", "Money Line"]:
            mkt = _parse_moneyline(outcomes)
            if mkt:
                markets.append(mkt)

        # Spread / Handicap
        elif "Handicap" in label or "Spread" in label or "Point Spread" in label:
            mkt = _parse_spread(outcomes)
            if mkt:
                markets.append(mkt)

        # Totals
        elif label in ["Total Goals", "Total Points", "Total", "Total Runs",
                        "Total Games", "Total Rounds"]:
            mkt = _parse_total(outcomes)
            if mkt:
                markets.append(mkt)
        elif "Over/Under" in label:
            mkt = _parse_total(outcomes)
            if mkt:
                markets.append(mkt)

    if markets:
        base_event.markets = markets
    return base_event


def _parse_moneyline(outcomes: list) -> Optional[Market]:
    """Parse moneyline/match winner outcomes."""
    parsed = []
    for oc in outcomes:
        odds_raw = oc.get("odds")
        if not odds_raw:
            continue
        dec = _kambi_odds_to_decimal(odds_raw)
        american = _decimal_to_american(dec)
        parsed.append(Outcome(
            name=oc.get("label", oc.get("englishLabel", "?")),
            price_american=american,
            price_decimal=dec,
        ))
    if len(parsed) >= 2:
        return Market(market_type=MarketType.MONEYLINE, name="Moneyline", outcomes=parsed)
    return None


def _parse_spread(outcomes: list) -> Optional[Market]:
    """Parse handicap/spread outcomes."""
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
            price_american=american,
            price_decimal=dec,
            point=point,
        ))
    if len(parsed) >= 2:
        return Market(market_type=MarketType.SPREAD, name="Spread", outcomes=parsed)
    return None


def _parse_total(outcomes: list) -> Optional[Market]:
    """Parse total (over/under) outcomes."""
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
        # Normalize Over/Under labels
        oc_type = oc.get("type", "")
        if oc_type == "OT_OVER" or "over" in label.lower():
            label = "Over"
        elif oc_type == "OT_UNDER" or "under" in label.lower():
            label = "Under"
        parsed.append(Outcome(
            name=label,
            price_american=american,
            price_decimal=dec,
            point=point,
        ))
    if len(parsed) >= 2:
        return Market(market_type=MarketType.TOTAL, name="Total", outcomes=parsed)
    return None


async def _fetch_event_detail(client: httpx.AsyncClient, event_id: str) -> Optional[dict]:
    """Fetch full betoffer detail for a single event."""
    url = f"{KAMBI_BASE}/betoffer/event/{event_id}.json?lang=en_GB&market=GB"
    try:
        resp = await client.get(url, headers=HEADERS)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


async def fetch_sport(sport_key: str) -> List[SportsbookSnapshot]:
    """
    Fetch odds from ComeOn for a given sport.
    
    Args:
        sport_key: One of the keys from SPORT_MAP (e.g., 'basketball_nba', 'soccer_epl')
    
    Returns:
        List of SportsbookSnapshot with events and odds.
    """
    mapping = SPORT_MAP.get(sport_key)
    if not mapping:
        return []

    kambi_path = mapping["path"]
    league_filter = mapping.get("league_filter")

    # Step 1: Get event list
    list_url = f"{KAMBI_BASE}/listView/{kambi_path}.json?lang=en_GB&market=GB&useCombined=true"

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        try:
            resp = await client.get(list_url, headers=HEADERS)
            if resp.status_code != 200:
                return []
            data = resp.json()
        except Exception as e:
            print(f"[ComeOn] Error fetching {sport_key}: {e}")
            return []

        raw_events = data.get("events", [])
        if not raw_events:
            return []

        # Determine sport/league labels
        sport_label = kambi_path.replace("_", " ").title()
        if kambi_path == "american_football":
            sport_label = "Football"
        elif kambi_path == "ice_hockey":
            sport_label = "Hockey"
        elif kambi_path == "football":
            sport_label = "Soccer"

        league_label = league_filter or sport_label

        # Parse events and optionally filter by league
        events = []
        event_ids_for_detail = []

        for ev in raw_events:
            evt = ev.get("event", {})
            # League filtering
            if league_filter:
                event_path = evt.get("path", [])
                group = evt.get("group", "")
                event_name = evt.get("name", "")
                path_str = "/".join(p.get("englishName", "") if isinstance(p, dict) else str(p) for p in event_path) if event_path else ""
                if not any(league_filter.lower() in s.lower() for s in [path_str, group, event_name, str(event_path)]):
                    continue

            parsed = _parse_event_from_list(ev, sport_label, league_label)
            if parsed:
                events.append(parsed)
                event_ids_for_detail.append(parsed.event_id)

        # Step 2: Fetch full betoffer detail for up to 25 events
        if event_ids_for_detail:
            detail_tasks = [
                _fetch_event_detail(client, eid)
                for eid in event_ids_for_detail[:25]
            ]
            detail_results = await asyncio.gather(*detail_tasks, return_exceptions=True)

            for i, result in enumerate(detail_results):
                if isinstance(result, dict) and i < len(events):
                    events[i] = _parse_betoffer_detail(result, events[i])

    if not events:
        return []

    return [SportsbookSnapshot(
        sportsbook="ComeOn",
        sport=sport_label,
        league=league_label,
        fetched_at=datetime.now(timezone.utc),
        events=events,
    )]