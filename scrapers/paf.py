"""
PAF (Kambi CDN) Scraper
Uses the Kambi offering API via PAF operator code.
Same data structure as Unibet but different operator.
"""
import httpx
import asyncio
from datetime import datetime, timezone
from typing import List, Dict
from .models import SportsbookSnapshot, Event, Market, Outcome, MarketType

BASE = "https://eu-offering-api.kambicdn.com/offering/v2018/paf"

# Reuse same sport paths as Unibet
SPORT_PATHS = {
    "basketball_nba": "basketball/nba",
    "basketball_ncaab": "basketball/ncaa",
    "ice_hockey_nhl": "ice_hockey/nhl",
    "baseball_mlb": "baseball/mlb",
    "football_nfl": "american_football/nfl",
    "soccer_epl": "football/england/premier_league",
    "soccer_la_liga": "football/spain/la_liga",
    "soccer_bundesliga": "football/germany/bundesliga",
    "soccer_serie_a": "football/italy/serie_a",
    "soccer_ligue_1": "football/france/ligue_1",
    "soccer_mls": "football/usa/mls",
    "soccer_champions_league": "football/champions_league",
    "soccer_europa_league": "football/europa_league",
    "tennis": "tennis",
}

LEAGUE_NAMES = {
    "basketball_nba": "NBA",
    "basketball_ncaab": "NCAA Basketball",
    "ice_hockey_nhl": "NHL",
    "baseball_mlb": "MLB",
    "football_nfl": "NFL",
    "soccer_epl": "English Premier League",
    "soccer_la_liga": "La Liga",
    "soccer_bundesliga": "Bundesliga",
    "soccer_serie_a": "Serie A",
    "soccer_ligue_1": "Ligue 1",
    "soccer_mls": "MLS",
    "soccer_champions_league": "Champions League",
    "soccer_europa_league": "Europa League",
    "tennis": "Tennis",
}


def _kambi_odds_to_decimal(odds: int) -> float:
    return round(odds / 1000, 4)

def _decimal_to_american(decimal_odds: float) -> int:
    if decimal_odds >= 2.0:
        return int(round((decimal_odds - 1) * 100))
    elif decimal_odds > 1.0:
        return int(round(-100 / (decimal_odds - 1)))
    return 0

def _kambi_line_to_float(line: int) -> float:
    return round(line / 1000, 2)

def _parse_offer_type(offer: dict):
    offer_type = offer.get("betOfferType", {}).get("name", "")
    criterion = offer.get("criterion", {}).get("label", "")
    if offer_type == "Match" or "Moneyline" in criterion or "Winner" in criterion:
        return MarketType.MONEYLINE, "Moneyline"
    elif offer_type == "Handicap" or "Spread" in criterion or "Handicap" in criterion:
        return MarketType.SPREAD, "Spread"
    elif offer_type == "Over/Under" or "Total" in criterion or "Over/Under" in criterion:
        return MarketType.TOTAL, "Total"
    return MarketType.OTHER, criterion or offer_type

def _parse_outcomes(outcomes: list, home: str, away: str) -> List[Outcome]:
    result = []
    for oc in outcomes:
        odds_raw = oc.get("odds")
        if odds_raw is None:
            continue
        line_raw = oc.get("line")
        decimal_odds = _kambi_odds_to_decimal(odds_raw)
        american = _decimal_to_american(decimal_odds)
        point = _kambi_line_to_float(line_raw) if line_raw is not None else None
        oc_type = oc.get("type", "")
        label = oc.get("label", "")
        if oc_type == "OT_ONE" or label == home:
            name = home
        elif oc_type == "OT_TWO" or label == away:
            name = away
        elif oc_type == "OT_OVER" or "Over" in label:
            name = "Over"
        elif oc_type == "OT_UNDER" or "Under" in label:
            name = "Under"
        elif oc_type == "OT_CROSS" or "Draw" in label:
            name = "Draw"
        else:
            name = label
        result.append(Outcome(
            name=name, price_american=american,
            price_decimal=decimal_odds, point=point,
        ))
    return result


async def _fetch_events_list(client: httpx.AsyncClient, sport_path: str) -> List[dict]:
    try:
        r = await client.get(
            f"{BASE}/listView/{sport_path}.json",
            params={"lang": "en_GB", "market": "GB", "includeParticipants": "true"},
            timeout=15,
        )
        if r.status_code == 200:
            return r.json().get("events", [])
    except Exception:
        pass
    return []


async def _fetch_event_detail(client: httpx.AsyncClient, event_id: int) -> List[dict]:
    try:
        r = await client.get(
            f"{BASE}/betoffer/event/{event_id}.json",
            params={"lang": "en_GB", "market": "GB"},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get("betOffers", [])
    except Exception:
        pass
    return []


async def fetch_sport(sport: str) -> List[SportsbookSnapshot]:
    sport_path = SPORT_PATHS.get(sport)
    if sport_path is None:
        return []
    league_name = LEAGUE_NAMES.get(sport, sport)

    async with httpx.AsyncClient(
        headers={"Accept": "application/json"},
        follow_redirects=True,
    ) as client:
        raw_events = await _fetch_events_list(client, sport_path)
        if not raw_events:
            return []

        event_ids = []
        event_data_map = {}
        for ev in raw_events:
            event_info = ev.get("event", {})
            eid = event_info.get("id")
            if eid:
                event_ids.append(eid)
                event_data_map[eid] = event_info

        # Fetch details concurrently
        detail_tasks = [_fetch_event_detail(client, eid) for eid in event_ids[:20]]
        detail_results = await asyncio.gather(*detail_tasks, return_exceptions=True)

        offers_map: Dict[int, List[dict]] = {}
        for eid, result in zip(event_ids[:20], detail_results):
            if isinstance(result, list):
                offers_map[eid] = result

        events = []
        for eid in event_ids[:20]:
            event_info = event_data_map.get(eid, {})
            name = event_info.get("name", "")
            parts = name.split(" - ", 1)
            home = parts[0].strip() if parts else name
            away = parts[1].strip() if len(parts) == 2 else ""

            start_time = None
            start_str = event_info.get("start", "")
            if start_str:
                try:
                    start_time = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                except Exception:
                    pass

            is_live = event_info.get("openForLiveBetting", False) or False

            all_offers = offers_map.get(eid, [])
            event_markets = []
            seen_types = set()

            for offer in all_offers:
                market_type, market_name = _parse_offer_type(offer)
                if market_type == MarketType.OTHER:
                    continue
                type_key = f"{market_type.value}_{market_name}"
                if type_key in seen_types:
                    continue
                seen_types.add(type_key)
                outcomes = _parse_outcomes(offer.get("outcomes", []), home, away)
                if outcomes:
                    event_markets.append(Market(
                        market_type=market_type, name=market_name, outcomes=outcomes,
                    ))

            if not event_markets:
                continue

            events.append(Event(
                event_id=f"paf_{eid}",
                sport=sport, league=league_name,
                home_team=home, away_team=away,
                description=f"{away} @ {home}" if away else home,
                start_time=start_time, is_live=is_live,
                markets=event_markets,
            ))

        if not events:
            return []

        return [SportsbookSnapshot(
            sportsbook="paf",
            sport=sport, league=league_name,
            fetched_at=datetime.now(timezone.utc),
            events=events,
        )]


if __name__ == "__main__":
    async def test():
        for sport in ["basketball_nba", "ice_hockey_nhl", "soccer_epl"]:
            snapshots = await fetch_sport(sport)
            for snap in snapshots:
                print(f"\n{snap.sportsbook} | {sport}: {len(snap.events)} events")
                for ev in snap.events[:2]:
                    print(f"  {ev.description}")
                    for m in ev.markets:
                        outs = ", ".join(
                            f"{o.name}={o.price_american}" + (f" @{o.point}" if o.point else "")
                            for o in m.outcomes
                        )
                        print(f"    {m.name}: {outs}")
    asyncio.run(test())