"""
FanDuel Sportsbook Scraper - Comprehensive Market Coverage Upgrade
Directly hits FanDuel's public sportsbook API for odds data.
Enhanced to capture and properly classify ALL available markets.
"""

import httpx
from datetime import datetime, timezone
from typing import List, Optional
from .models import (
    SportsbookSnapshot, Event, Market, Outcome, MarketType
)

SPORTSBOOK_NAME = "FanDuel"

BASE_URL = "https://sbapi.il.sportsbook.fanduel.com/api/content-managed-page"
API_KEY = "FhMFpcPWXMeyZxOx"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# FanDuel page IDs -> our normalized sport/league names
SPORT_MAP = {
    "nfl": {"sport": "Football", "league": "NFL"},
    "nba": {"sport": "Basketball", "league": "NBA"},
    "mlb": {"sport": "Baseball", "league": "MLB"},
    "nhl": {"sport": "Hockey", "league": "NHL"},
    "ncaaf": {"sport": "Football", "league": "NCAAF"},
    "ncaab": {"sport": "Basketball", "league": "NCAAB"},
    "wnba": {"sport": "Basketball", "league": "WNBA"},
    "mls": {"sport": "Soccer", "league": "MLS"},
    "epl": {"sport": "Soccer", "league": "EPL"},
    "champions-league": {"sport": "Soccer", "league": "Champions League"},
    "golf": {"sport": "Golf", "league": "PGA"},
    "ufc": {"sport": "MMA", "league": "UFC"},
    "boxing": {"sport": "Boxing", "league": "Boxing"},
    "tennis": {"sport": "Tennis", "league": "Tennis"},
}


def _classify_market(market_type_raw: str, market_name: str) -> MarketType:
    """
    Enhanced market classification for FanDuel.
    Properly detects player props, team props, game props, and alternate lines.
    """
    name_lower = market_name.lower()
    type_lower = market_type_raw.lower() if market_type_raw else ""
    
    # Combine market type and name for better classification
    combined_text = f"{name_lower} {type_lower}"
    
    # PLAYER PROPS - Detect player-specific betting markets
    player_prop_keywords = [
        # Basketball props
        'to score', 'to record', 'points', 'rebounds', 'assists', 'threes', 'made threes',
        'three pointers', 'three point', '3-point', '3 point', 'blocks', 'steals',
        'turnovers', 'double double', 'triple double', 'points + rebounds', 'points + assists',
        'rebounds + assists', 'p+r', 'p+a', 'r+a', 'points/rebounds/assists',
        # Football props
        'passing yards', 'passing touchdowns', 'rushing yards', 'rushing touchdowns',
        'receiving yards', 'receiving touchdowns', 'completions', 'interceptions',
        'sacks', 'tackles', 'tackles + assists', 'first downs', 'touchdowns scored',
        # Baseball props
        'total bases', 'hits', 'home runs', 'runs batted in', 'strikeouts',
        'hits allowed', 'runs allowed', 'innings pitched', 'strikeouts thrown',
        # Hockey props
        'goals', 'shots on goal', 'saves', 'first period goal', 'anytime',
        'last goal', 'goals scored',
        # Tennis props
        'aces', 'double faults', 'games won', 'sets won', 'break points',
        # General player indicators
        'player', 'performance', 'to make', 'to be', 'to have',
    ]
    
    if any(keyword in combined_text for keyword in player_prop_keywords):
        return MarketType.PLAYER_PROP
    
    # TEAM PROPS - Team-specific performance markets
    # Map to PLAYER_PROP since they're both prop bets
    team_prop_keywords = [
        'team to score', 'team to score first', 'team to score last',
        'team to score most', 'team total', 'team points',
        'first basket', 'first field goal', 'first touchdown',
        'highest scoring quarter', 'highest scoring half',
        'team with most', 'team leads at', 'race to',
        'to win by', 'winning margin', 'exact score',
        'quarter', 'period', 'inning', 'half',
    ]
    
    if any(keyword in combined_text for keyword in team_prop_keywords):
        return MarketType.PLAYER_PROP  # Map to PLAYER_PROP for now
    
    # GAME PROPS - Game-specific markets
    # Map to OTHER for now
    game_prop_keywords = [
        'alternatives', 'alternate', 'both teams score', 'btts',
        'draw no bet', 'double chance', 'total points', 'total goals',
        'total runs', 'total score', 'will the game go to',
        'overtime', 'first to', 'last to', 'special', 'novelty',
    ]
    
    if any(keyword in combined_text for keyword in game_prop_keywords):
        return MarketType.OTHER  # Map to OTHER for now
    
    # CORE MARKETS
    if "moneyline" in name_lower or "money line" in name_lower or "match_betting" in type_lower:
        return MarketType.MONEYLINE
    elif "spread" in name_lower or "handicap" in name_lower:
        return MarketType.SPREAD
    elif "total" in name_lower or "over/under" in name_lower or "over_under" in type_lower:
        return MarketType.TOTAL
    elif "future" in name_lower or "outright" in name_lower or "winner" in name_lower or "championship" in name_lower:
        return MarketType.FUTURES
    
    return MarketType.OTHER


def _safe_american_odds(raw_value) -> Optional[int]:
    """Safely parse American odds from FanDuel - can be int or str."""
    if raw_value is None:
        return None
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, float):
        return int(raw_value)
    if isinstance(raw_value, str):
        if raw_value == "EVEN":
            return 100
        try:
            return int(raw_value.replace("+", ""))
        except (ValueError, TypeError):
            return None
    return None


def _parse_response(data: dict, sport: str, league: str) -> List[Event]:
    """
    Parse FanDuel API response into Event models.
    Captures ALL available markets with enhanced classification.
    """
    attachments = data.get("attachments", {})
    raw_events = attachments.get("events", {})
    raw_markets = attachments.get("markets", {})

    # Build event_id -> markets mapping
    event_markets = {}
    for mid, mkt in raw_markets.items():
        eid = str(mkt.get("eventId", ""))
        if eid not in event_markets:
            event_markets[eid] = []
        event_markets[eid].append(mkt)

    events = []
    for eid, ev in raw_events.items():
        ev_name = ev.get("name", "")
        open_date = ev.get("openDate", "")

        # Parse start time
        start_time = None
        if open_date:
            try:
                if isinstance(open_date, str):
                    start_time = datetime.fromisoformat(open_date.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        # Skip far-future placeholder events
        if start_time and start_time.year > 2090:
            continue

        # Parse teams from event name
        home_team = ""
        away_team = ""
        if " @ " in ev_name:
            parts = ev_name.split(" @ ")
            away_team = parts[0].strip()
            home_team = parts[1].strip()
        elif " v " in ev_name:
            parts = ev_name.split(" v ")
            home_team = parts[0].strip()
            away_team = parts[1].strip()
        elif " vs " in ev_name:
            parts = ev_name.split(" vs ")
            home_team = parts[0].strip()
            away_team = parts[1].strip()
        else:
            home_team = ev_name
            away_team = ""

        # Parse ALL markets for this event (no filtering)
        markets = []
        for raw_mkt in event_markets.get(eid, []):
            mkt_name = raw_mkt.get("marketName", "")
            mkt_type_raw = raw_mkt.get("marketType", "")
            
            # Use enhanced classification
            market_type = _classify_market(mkt_type_raw, mkt_name)

            outcomes = []
            for runner in raw_mkt.get("runners", []):
                runner_name = runner.get("runnerName", "")
                odds_data = runner.get("winRunnerOdds", {})

                # American odds - handle both int and str
                raw_american = odds_data.get("americanDisplayOdds", {}).get("americanOdds")
                american_int = _safe_american_odds(raw_american)

                # Decimal odds
                decimal_val = None
                true_odds = odds_data.get("trueOdds", {}).get("decimalOdds", {})
                if true_odds:
                    try:
                        raw_decimal = true_odds.get("decimalOdds", 0)
                        decimal_val = float(raw_decimal) if raw_decimal else None
                    except (ValueError, TypeError):
                        decimal_val = None

                # Handicap/point - handle both int and float
                handicap = runner.get("handicap")
                point_val = None
                if handicap is not None:
                    try:
                        point_val = float(handicap)
                    except (ValueError, TypeError):
                        point_val = None

                if american_int is not None or decimal_val is not None:
                    outcomes.append(Outcome(
                        name=runner_name,
                        price_american=american_int,
                        price_decimal=decimal_val,
                        point=point_val,
                    ))

            if outcomes:
                markets.append(Market(
                    market_type=market_type,
                    name=mkt_name,
                    outcomes=outcomes,
                ))

        if markets:
            events.append(Event(
                event_id=eid,
                sport=sport,
                league=league,
                home_team=home_team,
                away_team=away_team,
                description=ev_name,
                start_time=start_time,
                is_live=ev.get("inPlay", False),
                markets=markets,
            ))

    return events


async def fetch_sport(sport_slug: str, client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    """
    Fetch odds for a FanDuel sport page.
    Captures all available markets with enhanced classification.
    """
    close_client = False
    if client is None:
        from ._proxy import get_client_kwargs
        client = httpx.AsyncClient(headers=HEADERS, timeout=30.0, **get_client_kwargs("US"))
        close_client = True

    snapshots = []
    try:
        sport_info = SPORT_MAP.get(sport_slug, {"sport": sport_slug.upper(), "league": sport_slug.upper()})
        params = {
            "page": "CUSTOM",
            "customPageId": sport_slug,
            "_ak": API_KEY,
        }
        resp = await client.get(BASE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        events = _parse_response(data, sport_info["sport"], sport_info["league"])
        now = datetime.now(timezone.utc)

        if events:
            snapshots.append(SportsbookSnapshot(
                sportsbook=SPORTSBOOK_NAME,
                sport=sport_info["sport"],
                league=sport_info["league"],
                fetched_at=now,
                events=events,
            ))
    except Exception as e:
        print(f"[FanDuel] Error fetching {sport_slug}: {e}")
    finally:
        if close_client:
            await client.aclose()

    return snapshots


async def fetch_all() -> List[SportsbookSnapshot]:
    """Fetch odds for all supported sports from FanDuel."""
    all_snapshots = []
    from ._proxy import get_client_kwargs
    async with httpx.AsyncClient(headers=HEADERS, timeout=30.0, **get_client_kwargs("US")) as client:
        for sport_slug in SPORT_MAP.keys():
            snapshots = await fetch_sport(sport_slug, client)
            all_snapshots.extend(snapshots)
    return all_snapshots


async def fetch_nfl(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("nfl", client)


async def fetch_nba(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("nba", client)


async def fetch_mlb(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("mlb", client)


async def fetch_nhl(client: Optional[httpx.AsyncClient] = None) -> List[SportsbookSnapshot]:
    return await fetch_sport("nhl", client)