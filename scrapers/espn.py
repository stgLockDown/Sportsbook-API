"""
ESPN Core API Scraper
=====================
ESPN provides odds data from DraftKings through their Core API.
The API uses nested $ref links that need to be resolved.

Provides: spreads, over/under, moneylines from DraftKings.
"""
import httpx
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, List
from scrapers.models import Event, Market, Outcome, MarketType, SportsbookSnapshot

logger = logging.getLogger(__name__)

BASE_URL = "https://sports.core.api.espn.com/v2/sports"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# ESPN sport/league path mappings
SPORT_LEAGUES = {
    "basketball": [
        ("basketball", "nba", "NBA"),
        ("basketball", "mens-college-basketball", "NCAAB"),
        ("basketball", "wnba", "WNBA"),
    ],
    "football": [
        ("football", "nfl", "NFL"),
        ("football", "college-football", "NCAAF"),
    ],
    "hockey": [
        ("hockey", "nhl", "NHL"),
    ],
    "baseball": [
        ("baseball", "mlb", "MLB"),
    ],
    "soccer": [
        ("soccer", "usa.1", "MLS"),
        ("soccer", "eng.1", "EPL"),
        ("soccer", "uefa.champions", "UCL"),
    ],
    "mma": [
        ("mma", "ufc", "UFC"),
    ],
}


def _american_to_decimal(american: int) -> float:
    """Convert American odds to decimal."""
    if american > 0:
        return round(1 + american / 100, 4)
    elif american < 0:
        return round(1 + 100 / abs(american), 4)
    return 1.0


async def _resolve_ref(client: httpx.AsyncClient, ref_url: str) -> Optional[dict]:
    """Resolve a $ref URL to get the actual data."""
    try:
        resp = await client.get(ref_url, headers=HEADERS)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.debug(f"ESPN ref resolve failed: {e}")
    return None


async def _fetch_odds_for_competition(client: httpx.AsyncClient, comp: dict) -> list[dict]:
    """Fetch odds data for a competition, resolving $ref links."""
    odds_data = comp.get("odds", [])

    if isinstance(odds_data, dict) and "$ref" in odds_data:
        resolved = await _resolve_ref(client, odds_data["$ref"])
        if resolved:
            items = resolved.get("items", [])
            odds_list = []
            for item in items:
                if isinstance(item, dict) and "$ref" in item:
                    detail = await _resolve_ref(client, item["$ref"])
                    if detail:
                        provider = detail.get("provider", {})
                        if isinstance(provider, dict) and "$ref" in provider:
                            prov_data = await _resolve_ref(client, provider["$ref"])
                            if prov_data:
                                detail["provider"] = prov_data
                        odds_list.append(detail)
                elif isinstance(item, dict):
                    odds_list.append(item)
            return odds_list
    elif isinstance(odds_data, list):
        return odds_data

    return []


def _parse_odds_to_markets(odds_list: list[dict]) -> List[Market]:
    """Parse ESPN odds data into our Market model."""
    markets = []

    for odds in odds_list:
        provider_name = odds.get("provider", {}).get("name", "Unknown")
        spread = odds.get("spread")
        over_under = odds.get("overUnder")
        home_odds = odds.get("homeTeamOdds", {})
        away_odds = odds.get("awayTeamOdds", {})

        # Moneyline
        home_ml = home_odds.get("moneyLine")
        away_ml = away_odds.get("moneyLine")
        if home_ml is not None and away_ml is not None:
            try:
                h = int(home_ml)
                a = int(away_ml)
                markets.append(Market(
                    market_type=MarketType.MONEYLINE,
                    name=f"Moneyline (via {provider_name})",
                    outcomes=[
                        Outcome(name="Home", price_american=h, price_decimal=_american_to_decimal(h), description=f"via {provider_name}"),
                        Outcome(name="Away", price_american=a, price_decimal=_american_to_decimal(a), description=f"via {provider_name}"),
                    ],
                ))
            except (ValueError, TypeError):
                pass

        # Spread
        if spread is not None:
            try:
                spread_val = float(spread)
                home_spread_odds = home_odds.get("spreadOdds")
                away_spread_odds = away_odds.get("spreadOdds")

                h_so = int(home_spread_odds) if home_spread_odds else -110
                a_so = int(away_spread_odds) if away_spread_odds else -110

                markets.append(Market(
                    market_type=MarketType.SPREAD,
                    name=f"Spread (via {provider_name})",
                    outcomes=[
                        Outcome(name="Home", price_american=h_so, price_decimal=_american_to_decimal(h_so), point=spread_val, description=f"via {provider_name}"),
                        Outcome(name="Away", price_american=a_so, price_decimal=_american_to_decimal(a_so), point=-spread_val, description=f"via {provider_name}"),
                    ],
                ))
            except (ValueError, TypeError):
                pass

        # Total (Over/Under)
        if over_under is not None:
            try:
                total_val = float(over_under)
                over_odds_val = odds.get("overOdds") or home_odds.get("overOdds")
                under_odds_val = odds.get("underOdds") or away_odds.get("underOdds")

                ov = int(over_odds_val) if over_odds_val else -110
                un = int(under_odds_val) if under_odds_val else -110

                markets.append(Market(
                    market_type=MarketType.TOTAL,
                    name=f"Total (via {provider_name})",
                    outcomes=[
                        Outcome(name="Over", price_american=ov, price_decimal=_american_to_decimal(ov), point=total_val, description=f"via {provider_name}"),
                        Outcome(name="Under", price_american=un, price_decimal=_american_to_decimal(un), point=total_val, description=f"via {provider_name}"),
                    ],
                ))
            except (ValueError, TypeError):
                pass

    return markets


async def _fetch_league_events(sport_path: str, league_path: str, league_name: str, sport_key: str) -> List[Event]:
    """Fetch events for a specific ESPN sport/league."""
    url = f"{BASE_URL}/{sport_path}/leagues/{league_path}/events"
    params = {"limit": 50}

    events = []
    try:
        async with httpx.AsyncClient(timeout=30, headers=HEADERS) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                logger.warning(f"ESPN {league_name}: HTTP {resp.status_code}")
                return []

            data = resp.json()
            items = data.get("items", [])

            sem = asyncio.Semaphore(5)

            async def process_event_ref(item):
                async with sem:
                    ref = item.get("$ref", "")
                    if not ref:
                        return None

                    ev_data = await _resolve_ref(client, ref)
                    if not ev_data:
                        return None

                    name = ev_data.get("name", "")
                    status_data = ev_data.get("status", {})
                    status_type = status_data.get("type", {}).get("name", "")

                    date_str = ev_data.get("date", "")
                    start_time = None
                    if date_str:
                        try:
                            start_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        except (ValueError, TypeError):
                            pass

                    is_live = status_type in ["STATUS_IN_PROGRESS", "STATUS_HALFTIME"]

                    competitions = ev_data.get("competitions", [])
                    if not competitions:
                        return None

                    comp = competitions[0]
                    competitors = comp.get("competitors", [])

                    home_team = ""
                    away_team = ""
                    for c in competitors:
                        team_data = c.get("team", {})
                        team_name = team_data.get("displayName", "") or team_data.get("name", "") or team_data.get("shortDisplayName", "") or team_data.get("abbreviation", "")
                        home_away = c.get("homeAway", "")

                        if home_away == "home":
                            home_team = team_name
                        elif home_away == "away":
                            away_team = team_name

                    if not home_team and not away_team:
                        if " at " in name:
                            parts = name.split(" at ", 1)
                            away_team = parts[0].strip()
                            home_team = parts[1].strip()
                        elif " vs " in name:
                            parts = name.split(" vs ", 1)
                            home_team = parts[0].strip()
                            away_team = parts[1].strip()
                        else:
                            return None

                    odds_list = await _fetch_odds_for_competition(client, comp)
                    markets = _parse_odds_to_markets(odds_list)

                    if not markets:
                        return None

                    return Event(
                        event_id=str(ev_data.get("id", "")),
                        sport=sport_key,
                        league=league_name,
                        home_team=home_team,
                        away_team=away_team,
                        description=f"{away_team} @ {home_team}",
                        start_time=start_time,
                        is_live=is_live,
                        markets=markets,
                    )

            tasks = [process_event_ref(item) for item in items[:20]]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Event):
                    events.append(result)
                elif isinstance(result, Exception):
                    logger.debug(f"ESPN event processing error: {result}")

    except Exception as e:
        logger.error(f"ESPN {league_name} error: {e}")

    logger.info(f"ESPN {league_name}: {len(events)} events with odds")
    return events


async def fetch_sport(sport: str) -> List[SportsbookSnapshot]:
    """Fetch events for a sport from ESPN."""
    leagues = SPORT_LEAGUES.get(sport, [])
    if not leagues:
        return []

    all_events = []
    for sport_path, league_path, league_name in leagues:
        events = await _fetch_league_events(sport_path, league_path, league_name, sport)
        all_events.extend(events)
        await asyncio.sleep(0.3)

    logger.info(f"ESPN/DraftKings: {len(all_events)} total {sport} events")

    if not all_events:
        return []

    return [SportsbookSnapshot(
        sportsbook="ESPN/DraftKings",
        sport=sport,
        league=sport,
        fetched_at=datetime.now(timezone.utc),
        events=all_events,
    )]