"""
Kambi Sportsbook Scraper
========================
Kambi powers: Unibet, 888sport, BetRivers, SugarHouse, Paf, LeoVegas,
Betsson, NordicBet, ComeOn, Rizk, Betsafe, Mr Green, Napoleon, and more.

Uses the Kambi Offering API via Unibet operator code.
Two approaches:
  1. listView - for getting match events by sport path
  2. betoffer/group - for getting events + odds by group/league ID
"""
import httpx
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, List
from scrapers.models import Event, Market, Outcome, MarketType, SportsbookSnapshot

logger = logging.getLogger(__name__)

BASE_URL = "https://eu-offering-api.kambicdn.com/offering/v2018/ub"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

# Sport path mappings for listView endpoint
SPORT_PATHS = {
    "basketball": "basketball",
    "football": "american_football",
    "baseball": "baseball",
    "hockey": "ice_hockey",
    "soccer": "football",
    "tennis": "tennis",
    "golf": "golf",
    "boxing": "boxing",
    "mma": "ufc_mma",
    "rugby": "rugby_union",
    "cricket": "cricket",
    "darts": "darts",
    "table_tennis": "table_tennis",
    "volleyball": "volleyball",
    "handball": "handball",
    "esports": "esports",
    "cycling": "cycling",
    "snooker": "snooker",
    "aussie_rules": "australian_rules",
    "rugby_league": "rugby_league",
    "motor_sports": "motorsports",
    "lacrosse": "lacrosse",
}

# Sport group IDs (top-level) for betoffer/group endpoint
SPORT_GROUP_IDS = {
    "basketball": 1000093204,
    "hockey": 1000093191,
    "baseball": 1000093211,
    "football": 1000093199,
    "tennis": 1000093193,
    "soccer": 1000093190,
    "golf": 1000093187,
    "mma": 1000093238,
}


def _parse_american_odds(odds_str) -> Optional[int]:
    """Parse American odds from Kambi (can be str or int)."""
    if odds_str is None or odds_str == "":
        return None
    try:
        s = str(odds_str).strip()
        if s.startswith("+"):
            return int(s[1:])
        return int(s)
    except (ValueError, TypeError):
        return None


def _american_to_decimal(american: int) -> float:
    """Convert American odds to decimal."""
    if american > 0:
        return round(1 + american / 100, 4)
    elif american < 0:
        return round(1 + 100 / abs(american), 4)
    return 1.0


def _parse_line(line_val) -> Optional[float]:
    """Parse Kambi line value (stored as integer * 1000)."""
    if line_val is None:
        return None
    try:
        return float(line_val) / 1000.0
    except (ValueError, TypeError):
        return None


def _classify_market(criterion_label: str) -> Optional[MarketType]:
    """Classify a Kambi criterion label into our MarketType."""
    label_lower = criterion_label.lower()

    if "moneyline" in label_lower:
        return MarketType.MONEYLINE
    if label_lower == "match":
        return MarketType.MONEYLINE
    if "spread" in label_lower or "handicap" in label_lower or "puck line" in label_lower or "run line" in label_lower:
        return MarketType.SPREAD
    if "total" in label_lower or "over/under" in label_lower:
        return MarketType.TOTAL
    if "1x2" in label_lower or "full time" in label_lower:
        return MarketType.MONEYLINE  # 3-way moneyline

    # Skip futures/props/exotic
    skip_keywords = ["winner", "champion", "mvp", "rookie", "defensive", "finishing",
                     "division", "conference", "first overall", "second overall",
                     "first wide receiver", "odd/even", "to be champion"]
    for kw in skip_keywords:
        if kw in label_lower:
            return None

    return None


def _parse_event_and_offers(event_data: dict, bet_offers: list, sport: str) -> Optional[Event]:
    """Parse a Kambi event with its bet offers into our Event model."""
    try:
        name = event_data.get("name", "")
        home_name = event_data.get("homeName", "")
        away_name = event_data.get("awayName", "")
        event_id = str(event_data.get("id", ""))
        start_str = event_data.get("start", "")
        state = event_data.get("state", "")

        # Skip non-match events (futures, specials)
        if not home_name and not away_name:
            if " - " in name:
                parts = name.split(" - ", 1)
                home_name = parts[0].strip()
                away_name = parts[1].strip()
            elif " vs " in name.lower():
                parts = name.lower().split(" vs ", 1)
                home_name = parts[0].strip().title()
                away_name = parts[1].strip().title()
            elif " @ " in name:
                parts = name.split(" @ ", 1)
                away_name = parts[0].strip()
                home_name = parts[1].strip()
            else:
                return None

        # Parse start time
        start_time = None
        if start_str:
            try:
                start_time = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        is_live = state == "STARTED"

        # Determine league
        league = ""
        group_path = event_data.get("path", [])
        if isinstance(group_path, list) and len(group_path) >= 2:
            league = "/".join(str(p.get("name", "")) for p in group_path[-2:] if isinstance(p, dict))
        if not league:
            league = event_data.get("group", "") or event_data.get("groupName", sport.upper())

        # Parse bet offers into markets
        markets = []
        for bo in bet_offers:
            criterion = bo.get("criterion", {})
            criterion_label = criterion.get("label", "")
            if not criterion_label:
                continue

            market_type = _classify_market(criterion_label)
            if market_type is None:
                continue

            outcomes = []
            for oc in bo.get("outcomes", []):
                label = oc.get("label", "")
                odds_american_raw = oc.get("oddsAmerican", "")
                line_raw = oc.get("line")

                parsed_odds = _parse_american_odds(odds_american_raw)
                parsed_line = _parse_line(line_raw)

                if parsed_odds is not None:
                    outcomes.append(Outcome(
                        name=label,
                        price_american=parsed_odds,
                        price_decimal=_american_to_decimal(parsed_odds),
                        point=parsed_line,
                        description=criterion_label,
                    ))

            if outcomes:
                markets.append(Market(
                    market_type=market_type,
                    name=criterion_label,
                    outcomes=outcomes,
                ))

        if not markets:
            return None

        return Event(
            event_id=event_id,
            sport=sport,
            league=league,
            home_team=home_name,
            away_team=away_name,
            description=f"{away_name} @ {home_name}",
            start_time=start_time,
            is_live=is_live,
            markets=markets,
        )
    except Exception as e:
        logger.error(f"Error parsing Kambi event: {e}")
        return None


async def fetch_events_listview(sport: str, client: httpx.AsyncClient) -> List[Event]:
    """Fetch events using the listView endpoint (all events for a sport)."""
    sport_path = SPORT_PATHS.get(sport)
    if not sport_path:
        return []

    url = f"{BASE_URL}/listView/{sport_path}/all/all/all/matches.json"
    params = {"lang": "en_US", "market": "US"}

    events = []
    try:
        resp = await client.get(url, params=params)
        if resp.status_code != 200:
            logger.debug(f"Kambi listView {sport}: HTTP {resp.status_code}")
            return []

        data = resp.json()
        raw_events = data.get("events", [])

        for ev_data in raw_events:
            event_info = ev_data.get("event", {})
            bet_offers = ev_data.get("betOffers", [])
            parsed = _parse_event_and_offers(event_info, bet_offers, sport)
            if parsed:
                events.append(parsed)

    except Exception as e:
        logger.error(f"Kambi listView error for {sport}: {e}")

    return events


async def fetch_events_group(sport: str, client: httpx.AsyncClient) -> List[Event]:
    """Fetch events using the betoffer/group endpoint (by sport group ID)."""
    group_id = SPORT_GROUP_IDS.get(sport)
    if not group_id:
        return []

    url = f"{BASE_URL}/betoffer/group/{group_id}.json"
    params = {"lang": "en_US", "market": "US", "range_size": 100}

    events = []
    try:
        resp = await client.get(url, params=params)
        if resp.status_code != 200:
            logger.debug(f"Kambi group {sport}: HTTP {resp.status_code}")
            return []

        data = resp.json()
        raw_events = data.get("events", [])
        raw_offers = data.get("betOffers", [])

        # Group offers by event ID
        offers_by_event = {}
        for bo in raw_offers:
            eid = bo.get("eventId")
            if eid:
                offers_by_event.setdefault(eid, []).append(bo)

        for ev_data in raw_events:
            event_id = ev_data.get("id")
            event_offers = offers_by_event.get(event_id, [])
            parsed = _parse_event_and_offers(ev_data, event_offers, sport)
            if parsed:
                events.append(parsed)

    except Exception as e:
        logger.error(f"Kambi group error for {sport}: {e}")

    return events


async def fetch_sport(sport: str) -> List[SportsbookSnapshot]:
    """Main entry point - fetch events for a sport from Kambi/Unibet."""
    async with httpx.AsyncClient(timeout=30, headers=HEADERS) as client:
        # Try listView first (better for match events with inline odds)
        events = await fetch_events_listview(sport, client)

        if not events:
            # Fall back to group endpoint
            events = await fetch_events_group(sport, client)

    logger.info(f"Kambi/Unibet: {len(events)} {sport} events")

    if not events:
        return []

    return [SportsbookSnapshot(
        sportsbook="Kambi/Unibet",
        sport=sport,
        league=sport,
        fetched_at=datetime.now(timezone.utc),
        events=events,
    )]