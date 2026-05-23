"""
The Odds API meta-provider.

Brings in odds from 80+ US/UK/EU/AU sportsbooks via the commercial
https://the-odds-api.com aggregator. Set env var THE_ODDS_API_KEY
to enable; otherwise this scraper no-ops (returns []).

The Odds API free tier: 500 requests/month (enough for ~15 refreshes
of major sports per day). Paid tier from $29/mo for 20k req/month.

Bookmakers unlocked (partial list):
  US:  DraftKings, FanDuel, BetMGM, Caesars, BetRivers, PointsBet, WynnBET,
       SugarHouse, Unibet US, BetOnline, LowVig, MyBookie, Bovada, Superbook
  UK:  bet365, William Hill, Paddy Power, Betfair, Ladbrokes UK, Coral UK,
       Boyle Sports, BetVictor, Skybet, Grosvenor, Marathon Bet, Matchbook,
       Smarkets, Betfred
  EU:  Betsson, Nordicbet, LeoVegas, 888sport, Unibet EU, Pinnacle, etc.
  AU:  Sportsbet AU, TAB AU, PlayUp, Ladbrokes AU, Neds, Bluebet, Boombet

This single integration adds ~40 books in one shot.
"""
import os
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Optional

import httpx

from .models import SportsbookSnapshot, Event, Market, Outcome, MarketType
from ._proxy import get_client_kwargs

API_KEY = os.getenv("THE_ODDS_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4"

# Our sport keys -> The Odds API sport keys
SPORT_KEY_MAP = {
    "basketball_nba":  "basketball_nba",
    "basketball_ncaab":"basketball_ncaab",
    "basketball_wnba": "basketball_wnba",
    "football_nfl":    "americanfootball_nfl",
    "football_ncaaf":  "americanfootball_ncaaf",
    "baseball_mlb":    "baseball_mlb",
    "ice_hockey_nhl":  "icehockey_nhl",
    "soccer_epl":      "soccer_epl",
    "soccer":          "soccer_uefa_champs_league",  # fallback
    "tennis":          "tennis_atp_aus_open_singles",  # fallback
    "mma_ufc":         "mma_mixed_martial_arts",
    "mma":             "mma_mixed_martial_arts",
    "boxing":          "boxing_boxing",
    "cricket":         "cricket_international_t20",
    "rugby":           "rugbyleague_nrl",
    "aussie_rules":    "aussierules_afl",
}


def _american_to_decimal(am: int) -> float:
    if am is None:
        return 0.0
    if am > 0:
        return round(1 + am / 100.0, 4)
    if am < 0:
        return round(1 + 100.0 / abs(am), 4)
    return 1.0


def _decimal_to_american(dec: float) -> int:
    if dec is None or dec <= 1:
        return 0
    if dec >= 2.0:
        return int(round((dec - 1) * 100))
    return int(round(-100 / (dec - 1)))


def _classify_market(key: str) -> MarketType:
    k = (key or "").lower()
    if "h2h" in k or "moneyline" in k:
        return MarketType.MONEYLINE
    if "spread" in k:
        return MarketType.SPREAD
    if "total" in k or "over_under" in k:
        return MarketType.TOTAL
    if any(p in k for p in ("player_", "batter_", "pitcher_")):
        return MarketType.PLAYER_PROP
    if any(p in k for p in ("team_total", "team_")):
        return MarketType.TEAM_PROP
    if "outright" in k or "future" in k:
        return MarketType.FUTURES
    return MarketType.OTHER


async def _fetch_odds(
    client: httpx.AsyncClient, sport_key_api: str
) -> List[dict]:
    url = f"{BASE_URL}/sports/{sport_key_api}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": "us,uk,eu,au",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }
    try:
        r = await client.get(url, params=params, timeout=25)
        if r.status_code == 200:
            return r.json() or []
        elif r.status_code in (401, 429):
            print(f"[TheOddsAPI] auth/rate-limit: status={r.status_code}")
        return []
    except Exception as e:
        print(f"[TheOddsAPI] fetch error: {e}")
        return []


def _parse_event(ev: dict, our_sport: str) -> Dict[str, Event]:
    """Parse a single event, returning {bookmaker_name: Event}."""
    home = ev.get("home_team", "")
    away = ev.get("away_team", "")
    commence = ev.get("commence_time")
    try:
        start_time = datetime.fromisoformat(commence.replace("Z", "+00:00"))
    except Exception:
        start_time = datetime.now(timezone.utc)

    sport_name = ev.get("sport_title", our_sport)
    event_id = ev.get("id", "")

    result: Dict[str, Event] = {}
    for bm in ev.get("bookmakers", []):
        bm_name = bm.get("title", bm.get("key", "unknown"))
        markets: List[Market] = []
        for mkt in bm.get("markets", []):
            mkey = mkt.get("key", "")
            mtype = _classify_market(mkey)
            outcomes: List[Outcome] = []
            for o in mkt.get("outcomes", []):
                name = o.get("name", "")
                price = o.get("price")
                point = o.get("point")
                if price is None:
                    continue
                outcomes.append(Outcome(
                    name=name,
                    odds_decimal=float(price),
                    odds_american=_decimal_to_american(float(price)),
                    line=float(point) if point is not None else None,
                ))
            if outcomes:
                markets.append(Market(
                    market_type=mtype,
                    name=mkey.replace("_", " ").title(),
                    outcomes=outcomes,
                ))
        if markets:
            result[bm_name] = Event(
                event_id=f"{event_id}_{bm_name}",
                sport=sport_name,
                league=sport_name,
                home_team=home,
                away_team=away,
                start_time=start_time,
                is_live=False,
                markets=markets,
            )
    return result


async def fetch_sport(sport_key: str) -> List[SportsbookSnapshot]:
    """Fetch all books for this sport via The Odds API aggregator."""
    if not API_KEY:
        return []
    api_sport = SPORT_KEY_MAP.get(sport_key)
    if not api_sport:
        return []

    async with httpx.AsyncClient(timeout=30, **get_client_kwargs("US")) as client:
        raw = await _fetch_odds(client, api_sport)

    # Group events by bookmaker
    per_book: Dict[str, List[Event]] = {}
    for ev in raw:
        book_events = _parse_event(ev, sport_key)
        for bm_name, event in book_events.items():
            per_book.setdefault(bm_name, []).append(event)

    # Build one SportsbookSnapshot per book
    snapshots: List[SportsbookSnapshot] = []
    for book_name, events in per_book.items():
        snapshots.append(SportsbookSnapshot(
            sportsbook=f"{book_name} (OddsAPI)",
            events=events,
            fetched_at=datetime.now(timezone.utc),
        ))

    return snapshots


# Direct call entry for the aggregator
async def fetch_all_for_sport(sport_key: str) -> List[SportsbookSnapshot]:
    return await fetch_sport(sport_key)


if __name__ == "__main__":
    async def test():
        if not API_KEY:
            print("Set THE_ODDS_API_KEY env var to test.")
            return
        snaps = await fetch_sport("basketball_nba")
        print(f"Books found: {len(snaps)}")
        for s in snaps[:5]:
            print(f"  {s.sportsbook}: {len(s.events)} events")

    asyncio.run(test())