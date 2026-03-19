"""
ActionNetwork Scraper — Meta-source providing odds from multiple major US sportsbooks.

ActionNetwork's scoreboard API returns odds from:
  - DraftKings (book_id 68)
  - FanDuel (book_id 69)
  - BetRivers (book_id 71)
  - BetMGM (book_id 75)
  - bet365 (book_id 79)
  - Caesars (book_id 123)
  - Consensus (book_id 15)
  - Opening Lines (book_id 30)
  
Sports: NBA, NHL, MLB, NFL, NCAAB, NCAAF, Soccer, MLS, EPL
"""

import httpx
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from scrapers.models import Event, Market, Outcome, SportsbookSnapshot, MarketType

# ── Book ID → Sportsbook Name Mapping ──────────────────────────────
BOOK_MAP: Dict[int, str] = {
    15: "consensus",
    30: "opening_lines",
    68: "draftkings_an",
    69: "fanduel_an",
    71: "betrivers_an",
    75: "betmgm",
    79: "bet365",
    123: "caesars",
    283: "betmgm_mi",
    347: "betmgm_va",
    972: "betrivers_ny",
    1: "betonline",
    3: "pinnacle_an",
    13: "caesars_nv",
    21: "bovada_an",
    24: "bet365_co",
    47: "golden_nugget",
    49: "caesars_nv2",
    74: "parx",
    78: "circa",
}

BOOK_DISPLAY: Dict[str, str] = {
    "draftkings_an": "DraftKings",
    "fanduel_an": "FanDuel",
    "betrivers_an": "BetRivers",
    "betmgm": "BetMGM",
    "bet365": "bet365",
    "caesars": "Caesars",
    "consensus": "Consensus",
    "opening_lines": "Opening Lines",
    "betonline": "BetOnline",
    "pinnacle_an": "Pinnacle",
    "bovada_an": "Bovada",
    "bet365_co": "bet365 CO",
    "golden_nugget": "Golden Nugget",
    "caesars_nv": "Caesars NV",
    "caesars_nv2": "Caesars NV",
    "parx": "Parx",
    "circa": "Circa",
    "betmgm_mi": "BetMGM MI",
    "betmgm_va": "BetMGM VA",
    "betrivers_ny": "BetRivers NY",
}

PRIMARY_BOOKS = {68, 69, 71, 75, 79, 123}

# ── Sport Slug Mapping ──────────────────────────────────────────────
SPORT_SLUGS: Dict[str, List[str]] = {
    "basketball_nba": ["nba"],
    "basketball_ncaab": ["ncaab"],
    "basketball_wnba": ["wnba"],
    "ice_hockey_nhl": ["nhl"],
    "baseball_mlb": ["mlb"],
    "american_football_nfl": ["nfl"],
    "american_football_ncaaf": ["ncaaf"],
    "soccer": ["soccer", "mls", "epl"],
    "soccer_epl": ["epl"],
    "soccer_mls": ["mls"],
    "soccer_champions_league": ["soccer"],
    "soccer_la_liga": ["soccer"],
    "soccer_bundesliga": ["soccer"],
    "soccer_serie_a": ["soccer"],
    "soccer_ligue_1": ["soccer"],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.actionnetwork.com/",
    "Origin": "https://www.actionnetwork.com",
}


def _american_to_decimal(american: Optional[int]) -> Optional[float]:
    """Convert American odds to decimal."""
    if american is None:
        return None
    if american > 0:
        return round(1 + american / 100, 4)
    else:
        return round(1 + 100 / abs(american), 4)


def _parse_game_odds(game: dict, book_id: int) -> List[Market]:
    """Parse odds for a specific book from a game's odds array."""
    odds_list = game.get("odds", [])
    markets: List[Market] = []

    book_odds = [o for o in odds_list if o.get("book_id") == book_id]
    if not book_odds:
        return markets

    teams = game.get("teams", [])
    home_team_id = game.get("home_team_id")
    away_team_id = game.get("away_team_id")
    home_team = ""
    away_team = ""
    teams_by_id = {t.get("id"): t for t in teams}
    if home_team_id and home_team_id in teams_by_id:
        home_team = teams_by_id[home_team_id].get("full_name", teams_by_id[home_team_id].get("short_name", "Home"))
    if away_team_id and away_team_id in teams_by_id:
        away_team = teams_by_id[away_team_id].get("full_name", teams_by_id[away_team_id].get("short_name", "Away"))
    # Fallback: first team = away, second = home (ActionNetwork convention)
    if not home_team and len(teams) >= 2:
        home_team = teams[0].get("full_name", "Home")
        away_team = teams[1].get("full_name", "Away")

    for odds_entry in book_odds:
        otype = odds_entry.get("type", "game")

        # ── Moneyline ──
        ml_home = odds_entry.get("ml_home")
        ml_away = odds_entry.get("ml_away")
        if ml_home is not None and ml_away is not None:
            outcomes = []
            outcomes.append(Outcome(
                name=home_team,
                price_decimal=_american_to_decimal(ml_home),
                price_american=int(ml_home),
            ))
            outcomes.append(Outcome(
                name=away_team,
                price_decimal=_american_to_decimal(ml_away),
                price_american=int(ml_away),
            ))
            ml_draw = odds_entry.get("ml_draw")
            if ml_draw is not None:
                outcomes.append(Outcome(
                    name="Draw",
                    price_decimal=_american_to_decimal(ml_draw),
                    price_american=int(ml_draw),
                ))
            markets.append(Market(
                market_type=MarketType.MONEYLINE,
                name=f"Moneyline ({otype})",
                outcomes=outcomes,
            ))

        # ── Spread ──
        spread_home = odds_entry.get("spread_home")
        spread_away = odds_entry.get("spread_away")
        spread_home_line = odds_entry.get("spread_home_line")
        spread_away_line = odds_entry.get("spread_away_line")
        if spread_home is not None and spread_away is not None:
            outcomes = []
            outcomes.append(Outcome(
                name=f"{home_team} {spread_home:+g}",
                price_decimal=_american_to_decimal(spread_home_line),
                price_american=int(spread_home_line) if spread_home_line else None,
                point=float(spread_home),
            ))
            outcomes.append(Outcome(
                name=f"{away_team} {spread_away:+g}",
                price_decimal=_american_to_decimal(spread_away_line),
                price_american=int(spread_away_line) if spread_away_line else None,
                point=float(spread_away),
            ))
            markets.append(Market(
                market_type=MarketType.SPREAD,
                name=f"Spread ({otype})",
                outcomes=outcomes,
            ))

        # ── Total ──
        total = odds_entry.get("total")
        over_line = odds_entry.get("over")
        under_line = odds_entry.get("under")
        if total is not None:
            outcomes = []
            outcomes.append(Outcome(
                name=f"Over {total}",
                price_decimal=_american_to_decimal(over_line),
                price_american=int(over_line) if over_line else None,
                point=float(total),
            ))
            outcomes.append(Outcome(
                name=f"Under {total}",
                price_decimal=_american_to_decimal(under_line),
                price_american=int(under_line) if under_line else None,
                point=float(total),
            ))
            markets.append(Market(
                market_type=MarketType.TOTAL,
                name=f"Total ({otype})",
                outcomes=outcomes,
            ))

    return markets


def _parse_game_meta(game: dict):
    """Extract game metadata using home_team_id / away_team_id."""
    teams = game.get("teams", [])
    home_team_id = game.get("home_team_id")
    away_team_id = game.get("away_team_id")
    home_team = ""
    away_team = ""
    teams_by_id = {t.get("id"): t for t in teams}
    if home_team_id and home_team_id in teams_by_id:
        home_team = teams_by_id[home_team_id].get("full_name", teams_by_id[home_team_id].get("short_name", "Home"))
    if away_team_id and away_team_id in teams_by_id:
        away_team = teams_by_id[away_team_id].get("full_name", teams_by_id[away_team_id].get("short_name", "Away"))
    # Fallback: first team = away, second = home
    if not home_team and len(teams) >= 2:
        home_team = teams[0].get("full_name", "Home")
        away_team = teams[1].get("full_name", "Away")
    start_time = game.get("start_time", "")
    status = game.get("status_display", "")
    return home_team, away_team, start_time, status


async def fetch_sport(sport: str) -> List[SportsbookSnapshot]:
    """
    Fetch odds from ActionNetwork for a given sport.
    Returns one SportsbookSnapshot per sportsbook found in the data.
    """
    slugs = SPORT_SLUGS.get(sport, [])
    if not slugs:
        base = sport.split("_")[-1] if "_" in sport else sport
        slugs = [base]

    all_games: List[dict] = []
    seen_game_ids = set()

    async with httpx.AsyncClient(timeout=20, headers=HEADERS) as client:
        for slug in slugs:
            try:
                url = f"https://api.actionnetwork.com/web/v1/scoreboard/{slug}"
                resp = await client.get(url)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                games = data.get("games", [])
                for g in games:
                    gid = g.get("id")
                    if gid and gid not in seen_game_ids:
                        seen_game_ids.add(gid)
                        all_games.append(g)
            except Exception:
                continue

    if not all_games:
        return []

    # Collect all unique book_ids
    all_book_ids: set = set()
    for g in all_games:
        for o in g.get("odds", []):
            bid = o.get("book_id")
            if bid is not None:
                all_book_ids.add(bid)

    now = datetime.now(timezone.utc)
    snapshots: List[SportsbookSnapshot] = []

    for book_id in sorted(all_book_ids):
        book_key = BOOK_MAP.get(book_id)
        if not book_key:
            book_key = f"actionnetwork_book_{book_id}"

        events: List[Event] = []
        for g in all_games:
            home_team, away_team, start_time, status = _parse_game_meta(g)
            markets = _parse_game_odds(g, book_id)
            if not markets:
                continue

            is_live = False
            if status and status.lower() not in ("", "scheduled", "pre-game", "final", "postponed"):
                is_live = True

            # Parse start_time
            st = None
            if start_time:
                try:
                    st = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                except Exception:
                    pass

            events.append(Event(
                event_id=f"an_{g.get('id', '')}",
                sport=sport,
                league=sport.upper(),
                home_team=home_team,
                away_team=away_team,
                description=f"{away_team} @ {home_team}",
                start_time=st,
                is_live=is_live,
                markets=markets,
            ))

        if events:
            snapshots.append(SportsbookSnapshot(
                sportsbook=book_key,
                sport=sport,
                league=sport.upper(),
                fetched_at=now,
                events=events,
            ))

    return snapshots


async def fetch_single_book(sport: str, book_key: str) -> Optional[SportsbookSnapshot]:
    """Fetch odds for a single book from ActionNetwork."""
    all_snapshots = await fetch_sport(sport)
    for snap in all_snapshots:
        if snap.sportsbook == book_key:
            return snap
    return None


def get_all_book_keys() -> List[str]:
    """Return all possible sportsbook keys from ActionNetwork."""
    return list(set(BOOK_MAP.values()))


def get_primary_book_keys() -> List[str]:
    """Return only the primary (major US) sportsbook keys."""
    return [BOOK_MAP[bid] for bid in PRIMARY_BOOKS if bid in BOOK_MAP]


# ── Test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    async def _test():
        for sport in ["basketball_nba", "ice_hockey_nhl", "baseball_mlb", "american_football_nfl", "soccer"]:
            print(f"\n{'='*60}")
            print(f"Sport: {sport}")
            print(f"{'='*60}")
            snaps = await fetch_sport(sport)
            for s in snaps:
                print(f"  {s.sportsbook:20s}: {len(s.events)} events")
                if s.events:
                    ev = s.events[0]
                    print(f"    Sample: {ev.away_team} @ {ev.home_team}")
                    for m in ev.markets[:3]:
                        print(f"      {m.market_type.value}: {m.name}")
                        for o in m.outcomes:
                            print(f"        {o.name}: dec={o.price_decimal} amer={o.price_american}")
    asyncio.run(_test())