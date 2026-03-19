"""
22Bet Scraper — International sportsbook with broad coverage.

Uses the LiveFeed/Get1x2_VZip endpoint which returns both live and prematch events.
Each "Value" entry is a game with team names at the top level and markets in "E" array.

Market type mapping:
  T=401, G=101 → Moneyline Win 1
  T=402, G=101 → Moneyline Win 2
  T=7,   G=2   → Handicap/Spread Team 1
  T=8,   G=2   → Handicap/Spread Team 2
  T=9,   G=17  → Total Over
  T=10,  G=17  → Total Under
  T=3653, G=2766 → 1X2 Win 1 (soccer)
  T=3654, G=2766 → 1X2 Draw (soccer)
  T=3655, G=2766 → 1X2 Win 2 (soccer)
  T=11,  G=15  → Individual Total 1 Over
  T=12,  G=15  → Individual Total 1 Under
  T=13,  G=62  → Individual Total 2 Over
  T=14,  G=62  → Individual Total 2 Under

Sports: Basketball(3), Ice Hockey(2), Baseball(6), Soccer(1), Tennis(4),
        American Football(12), MMA(22), Boxing(9)
"""

import httpx
import asyncio
from datetime import datetime, timezone
from typing import List, Optional
from scrapers.models import Event, Market, Outcome, SportsbookSnapshot, MarketType

# ── Sport ID Mapping ────────────────────────────────────────────────
SPORT_IDS = {
    "basketball_nba": 3,
    "basketball_ncaab": 3,
    "basketball_euroleague": 3,
    "basketball_wnba": 3,
    "ice_hockey_nhl": 2,
    "ice_hockey_khl": 2,
    "baseball_mlb": 6,
    "baseball_npb": 6,
    "american_football_nfl": 12,
    "american_football_ncaaf": 12,
    "soccer": 1,
    "soccer_epl": 1,
    "soccer_la_liga": 1,
    "soccer_bundesliga": 1,
    "soccer_serie_a": 1,
    "soccer_ligue_1": 1,
    "soccer_mls": 1,
    "soccer_champions_league": 1,
    "tennis": 4,
    "tennis_atp": 4,
    "tennis_wta": 4,
    "mma": 22,
    "boxing": 9,
    "table_tennis": 20,
    "volleyball": 19,
    "handball": 8,
    "rugby": 11,
    "cricket": 66,
    "esports": 40,
}

# League name filters per sport key (to narrow down results)
LEAGUE_FILTERS = {
    "basketball_nba": ["NBA"],
    "basketball_ncaab": ["NCAA", "NCAAB"],
    "basketball_wnba": ["WNBA"],
    "basketball_euroleague": ["Euroleague"],
    "ice_hockey_nhl": ["NHL"],
    "ice_hockey_khl": ["KHL"],
    "baseball_mlb": ["MLB"],
    "american_football_nfl": ["NFL"],
    "american_football_ncaaf": ["NCAA", "NCAAF"],
    "soccer_epl": ["Premier League", "England"],
    "soccer_la_liga": ["La Liga", "Spain"],
    "soccer_bundesliga": ["Bundesliga", "Germany"],
    "soccer_serie_a": ["Serie A", "Italy"],
    "soccer_ligue_1": ["Ligue 1", "France"],
    "soccer_mls": ["MLS"],
    "soccer_champions_league": ["Champions League"],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Accept": "application/json",
}

BASE_URL = "https://22bet.com/LiveFeed/Get1x2_VZip"


def _decimal_to_american(decimal_odds: float) -> Optional[int]:
    """Convert decimal odds to American."""
    if decimal_odds is None or decimal_odds <= 1:
        return None
    if decimal_odds >= 2.0:
        return int(round((decimal_odds - 1) * 100))
    else:
        return int(round(-100 / (decimal_odds - 1)))


def _parse_markets(game: dict) -> List[Market]:
    """Parse markets from a 22Bet game entry."""
    markets: List[Market] = []
    entries = game.get("E", [])
    if not entries:
        return markets

    team1 = game.get("O1", "Team 1")
    team2 = game.get("O2", "Team 2")

    # Index entries by type
    by_type = {}
    for e in entries:
        t = e.get("T")
        if t is not None:
            by_type[t] = e

    # ── Moneyline (T=401 Win1, T=402 Win2) ──
    w1 = by_type.get(401)
    w2 = by_type.get(402)
    if w1 and w2:
        outcomes = [
            Outcome(
                name=team1,
                price_decimal=w1.get("C"),
                price_american=_decimal_to_american(w1.get("C")),
            ),
            Outcome(
                name=team2,
                price_decimal=w2.get("C"),
                price_american=_decimal_to_american(w2.get("C")),
            ),
        ]
        markets.append(Market(
            market_type=MarketType.MONEYLINE,
            name="Moneyline",
            outcomes=outcomes,
        ))

    # ── 1X2 for soccer (T=3653 Win1, T=3654 Draw, T=3655 Win2) ──
    s1 = by_type.get(3653)
    sd = by_type.get(3654)
    s2 = by_type.get(3655)
    if s1 and s2:
        outcomes = [
            Outcome(
                name=team1,
                price_decimal=s1.get("C"),
                price_american=_decimal_to_american(s1.get("C")),
            ),
        ]
        if sd:
            outcomes.append(Outcome(
                name="Draw",
                price_decimal=sd.get("C"),
                price_american=_decimal_to_american(sd.get("C")),
            ))
        outcomes.append(Outcome(
            name=team2,
            price_decimal=s2.get("C"),
            price_american=_decimal_to_american(s2.get("C")),
        ))
        # Only add if we don't already have a moneyline
        if not (w1 and w2):
            markets.append(Market(
                market_type=MarketType.MONEYLINE,
                name="1X2",
                outcomes=outcomes,
            ))

    # ── Spread/Handicap (T=7 Team1, T=8 Team2) ──
    h1 = by_type.get(7)
    h2 = by_type.get(8)
    if h1 and h2:
        p1 = h1.get("P", 0)
        p2 = h2.get("P", 0)
        outcomes = [
            Outcome(
                name=f"{team1} {p1:+g}" if p1 else team1,
                price_decimal=h1.get("C"),
                price_american=_decimal_to_american(h1.get("C")),
                point=float(p1) if p1 else None,
            ),
            Outcome(
                name=f"{team2} {p2:+g}" if p2 else team2,
                price_decimal=h2.get("C"),
                price_american=_decimal_to_american(h2.get("C")),
                point=float(p2) if p2 else None,
            ),
        ]
        markets.append(Market(
            market_type=MarketType.SPREAD,
            name="Spread",
            outcomes=outcomes,
        ))

    # ── Total Over/Under (T=9 Over, T=10 Under) ──
    ov = by_type.get(9)
    un = by_type.get(10)
    if ov and un:
        total_line = ov.get("P", un.get("P", 0))
        outcomes = [
            Outcome(
                name=f"Over {total_line}",
                price_decimal=ov.get("C"),
                price_american=_decimal_to_american(ov.get("C")),
                point=float(total_line) if total_line else None,
            ),
            Outcome(
                name=f"Under {total_line}",
                price_decimal=un.get("C"),
                price_american=_decimal_to_american(un.get("C")),
                point=float(total_line) if total_line else None,
            ),
        ]
        markets.append(Market(
            market_type=MarketType.TOTAL,
            name="Total",
            outcomes=outcomes,
        ))

    return markets


def _matches_league_filter(league_name: str, sport: str) -> bool:
    """Check if a game's league matches the sport filter."""
    filters = LEAGUE_FILTERS.get(sport)
    if not filters:
        return True  # No filter = accept all
    league_lower = league_name.lower()
    return any(f.lower() in league_lower for f in filters)


async def fetch_sport(sport: str) -> List[SportsbookSnapshot]:
    """Fetch odds from 22Bet for a given sport."""
    sport_id = SPORT_IDS.get(sport)
    if sport_id is None:
        return []

    async with httpx.AsyncClient(timeout=20, headers=HEADERS) as client:
        try:
            url = f"{BASE_URL}?sports={sport_id}&count=200&lng=en&mode=4"
            resp = await client.get(url)
            if resp.status_code != 200:
                return []
            data = resp.json()
        except Exception:
            return []

    value = data.get("Value", [])
    if not value:
        return []

    now = datetime.now(timezone.utc)
    events: List[Event] = []

    for game in value:
        league_name = game.get("L", "")
        
        # Apply league filter
        if not _matches_league_filter(league_name, sport):
            continue

        team1 = game.get("O1", "")
        team2 = game.get("O2", "")
        if not team1 or not team2:
            continue

        markets = _parse_markets(game)
        if not markets:
            continue

        # Parse start time from Unix timestamp
        start_ts = game.get("S")
        start_time = None
        if start_ts:
            try:
                start_time = datetime.fromtimestamp(start_ts, tz=timezone.utc)
            except Exception:
                pass

        # Determine if live
        is_live = game.get("SS", 0) == 2

        game_id = game.get("I", "")

        events.append(Event(
            event_id=f"22bet_{game_id}",
            sport=sport,
            league=league_name or sport.upper(),
            home_team=team1,
            away_team=team2,
            description=f"{team1} vs {team2}",
            start_time=start_time,
            is_live=is_live,
            markets=markets,
        ))

    if not events:
        return []

    return [SportsbookSnapshot(
        sportsbook="twentytwobet",
        sport=sport,
        league=sport.upper(),
        fetched_at=now,
        events=events,
    )]


# ── Test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    async def _test():
        for sport in ["basketball_nba", "ice_hockey_nhl", "baseball_mlb",
                       "soccer", "soccer_epl", "tennis"]:
            print(f"\n{'='*60}")
            print(f"Sport: {sport}")
            print(f"{'='*60}")
            snaps = await fetch_sport(sport)
            for s in snaps:
                print(f"  {s.sportsbook}: {len(s.events)} events")
                for ev in s.events[:3]:
                    live_tag = " [LIVE]" if ev.is_live else ""
                    print(f"    {ev.home_team} vs {ev.away_team} ({ev.league}){live_tag}")
                    for m in ev.markets:
                        outs = ", ".join([f"{o.name}: {o.price_decimal}" for o in m.outcomes])
                        print(f"      {m.market_type.value}: {outs}")
    asyncio.run(_test())