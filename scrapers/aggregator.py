"""
Odds Aggregator v9
Fetches from all sportsbooks, caches results, matches events across books,
and finds best odds.

Supported sportsbooks (36+):
  US Legal:      FanDuel, BetRivers, ESPN/DraftKings, DraftKings (direct)
  US via AN:     DraftKings, FanDuel, BetRivers, BetMGM, bet365, Caesars
  Offshore:      Bovada
  Sharp:         Pinnacle, Pinnacle v3 (Arcadia), Pinnacle (Guest)
  EU/Intl:       Kambi/Unibet, Unibet (Kambi Detail), PAF (Kambi Detail),
                 PAF, Svenska Spel, ATG, Unibet UK, Unibet SE, Unibet NL, 22Bet
                 Coolbet, ComeOn, Leon.bet
  AU:            Ladbrokes AU, Neds AU, PointsBet
  Exchanges:     Smarkets, Matchbook
  DFS:           Underdog Fantasy
  Reference:     Consensus, Opening Lines
"""

import asyncio
import httpx
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple
from .models import (
    SportsbookSnapshot, Event, Market, Outcome, MarketType,
    AggregatedEvent, BestOdds
)
from . import bovada, fanduel, betrivers, pinnacle, kambi, espn, smarkets, matchbook
from . import ladbrokes_au, neds_au, kambi_multi, underdog, draftkings
from . import actionnetwork, twentytwobet, pointsbet
from . import pinnacle_v3, unibet, paf
from . import coolbet, leon, pinnacle_guest
from . import comeon


# ─── Cache ────────────────────────────────────────────────────────────

class OddsCache:
    """Simple in-memory cache with TTL."""

    def __init__(self, ttl_seconds: int = 300):
        self.ttl = timedelta(seconds=ttl_seconds)
        self._store: Dict[str, Tuple[datetime, list]] = {}

    def get(self, key: str) -> Optional[list]:
        if key in self._store:
            ts, data = self._store[key]
            if datetime.now(timezone.utc) - ts < self.ttl:
                return data
            del self._store[key]
        return None

    def set(self, key: str, data: list):
        self._store[key] = (datetime.now(timezone.utc), data)

    def clear(self):
        self._store.clear()

    def stats(self) -> dict:
        now = datetime.now(timezone.utc)
        active = 0
        expired = 0
        for key, (ts, _) in self._store.items():
            if now - ts < self.ttl:
                active += 1
            else:
                expired += 1
        return {
            "total_keys": len(self._store),
            "active": active,
            "expired": expired,
            "ttl_seconds": int(self.ttl.total_seconds()),
        }


cache = OddsCache(ttl_seconds=300)

# Sport slug mappings for aggregator v5
SPORT_SLUGS = {
    "nba": {
        "sport": "Basketball", "league": "NBA",
        "bovada": "basketball/nba", "fanduel": "nba", "betrivers": "basketball",
        "pinnacle_league": "NBA", "kambi": "basketball", "espn": "basketball",
        "smarkets": "basketball", "matchbook": "basketball",
        "ladbrokes_au": "nba", "neds_au": "nba", "kambi_multi": "nba",
        "underdog": "nba", "draftkings": "nba",
        "actionnetwork": "basketball_nba", "twentytwobet": "basketball_nba",
        "pointsbet": "basketball_nba",
        "pinnacle_v3": "basketball_nba", "unibet_detail": "basketball_nba", "paf_detail": "basketball_nba",
        "coolbet": "basketball_nba", "comeon": "basketball_nba", "leon": "basketball_nba", "pinnacle_guest": "basketball_nba",
    },
    "nfl": {
        "sport": "Football", "league": "NFL",
        "bovada": "football/nfl", "fanduel": "nfl", "betrivers": "football",
        "pinnacle_league": "NFL", "kambi": "football", "espn": "football",
        "smarkets": "football",
        "ladbrokes_au": "nfl", "neds_au": "nfl", "kambi_multi": "nfl",
        "underdog": "nfl", "draftkings": "nfl",
        "actionnetwork": "american_football_nfl", "twentytwobet": "american_football_nfl",
        "pointsbet": "american_football_nfl",
        "pinnacle_v3": "football_nfl", "unibet_detail": "football_nfl", "paf_detail": "football_nfl",
        "coolbet": "football_nfl", "comeon": "football_nfl", "leon": "football_nfl", "pinnacle_guest": "football_nfl",
    },
    "mlb": {
        "sport": "Baseball", "league": "MLB",
        "bovada": "baseball/mlb", "fanduel": "mlb", "betrivers": "baseball",
        "pinnacle_league": "MLB", "kambi": "baseball", "espn": "baseball",
        "smarkets": "baseball", "matchbook": "baseball",
        "ladbrokes_au": "mlb", "neds_au": "mlb", "kambi_multi": "mlb",
        "underdog": "mlb", "draftkings": "mlb",
        "actionnetwork": "baseball_mlb", "twentytwobet": "baseball_mlb",
        "pointsbet": "baseball_mlb",
        "pinnacle_v3": "baseball_mlb", "unibet_detail": "baseball_mlb", "paf_detail": "baseball_mlb",
        "coolbet": "baseball_mlb", "comeon": "baseball_mlb", "leon": "baseball_mlb", "pinnacle_guest": "baseball_mlb",
    },
    "nhl": {
        "sport": "Hockey", "league": "NHL",
        "bovada": "hockey/nhl", "fanduel": "nhl", "betrivers": "hockey",
        "pinnacle_league": "NHL", "kambi": "hockey", "espn": "hockey",
        "smarkets": "hockey",
        "ladbrokes_au": "nhl", "neds_au": "nhl", "kambi_multi": "nhl",
        "underdog": "nhl", "draftkings": "nhl",
        "actionnetwork": "ice_hockey_nhl", "twentytwobet": "ice_hockey_nhl",
        "pointsbet": "ice_hockey_nhl",
        "pinnacle_v3": "ice_hockey_nhl", "unibet_detail": "ice_hockey_nhl", "paf_detail": "ice_hockey_nhl",
        "coolbet": "ice_hockey_nhl", "comeon": "ice_hockey_nhl", "leon": "ice_hockey_nhl", "pinnacle_guest": "ice_hockey_nhl",
    },
    "ncaaf": {
        "sport": "Football", "league": "NCAAF",
        "bovada": "football/college-football", "fanduel": "ncaaf", "betrivers": "football",
        "pinnacle_league": "NCAAF", "kambi": "football", "espn": "football",
        "ladbrokes_au": "ncaaf", "neds_au": "ncaaf", "kambi_multi": "ncaaf",
        "underdog": "ncaaf", "draftkings": "ncaaf",
        "actionnetwork": "american_football_ncaaf",
        "coolbet": "football_ncaaf", "comeon": "football_ncaaf", "leon": "football_ncaaf", "pinnacle_guest": "football_ncaaf",
    },
    "ncaab": {
        "sport": "Basketball", "league": "NCAAB",
        "bovada": "basketball/college-basketball", "fanduel": "ncaab", "betrivers": "basketball",
        "pinnacle_league": "NCAAB", "kambi": "basketball", "espn": "basketball",
        "ladbrokes_au": "ncaab", "neds_au": "ncaab", "kambi_multi": "ncaab",
        "underdog": "ncaab", "draftkings": "ncaab",
        "actionnetwork": "basketball_ncaab", "twentytwobet": "basketball_ncaab",
        "pointsbet": "basketball_ncaab",
        "pinnacle_v3": "basketball_ncaab", "unibet_detail": "basketball_ncaab", "paf_detail": "basketball_ncaab",
        "coolbet": "basketball_ncaab", "comeon": "basketball_ncaab", "leon": "basketball_ncaab", "pinnacle_guest": "basketball_ncaab",
    },
    "soccer": {
        "sport": "Soccer", "league": "Soccer",
        "bovada": "soccer", "fanduel": "mls", "betrivers": "soccer",
        "pinnacle_sport": "soccer", "kambi": "soccer", "espn": "soccer",
        "smarkets": "soccer", "matchbook": "soccer",
        "ladbrokes_au": "soccer", "neds_au": "soccer", "kambi_multi": "soccer",
        "underdog": "soccer", "draftkings": "soccer",
        "actionnetwork": "soccer", "twentytwobet": "soccer",
        "pointsbet": "soccer_epl",
        "pinnacle_v3": "soccer_epl", "unibet_detail": "soccer_epl", "paf_detail": "soccer_epl",
        "coolbet": "soccer", "comeon": "soccer", "leon": "soccer", "pinnacle_guest": "soccer",
    },
    "mma": {
        "sport": "MMA", "league": "UFC",
        "bovada": "mma", "fanduel": "ufc", "betrivers": "mma",
        "pinnacle_league": "UFC", "kambi": "mma", "espn": "mma",
        "smarkets": "mma",
        "ladbrokes_au": "mma", "neds_au": "mma", "kambi_multi": "mma",
        "underdog": "mma", "draftkings": "mma",
        "twentytwobet": "mma", "pointsbet": "mma",
        "pinnacle_v3": "mma_ufc",
        "coolbet": "mma", "comeon": "mma", "leon": "mma_ufc", "pinnacle_guest": "mma_ufc",
    },
    "boxing": {
        "sport": "Boxing", "league": "Boxing",
        "bovada": "boxing", "fanduel": "boxing", "betrivers": "boxing",
        "pinnacle_sport": "boxing", "kambi": "boxing", "smarkets": "boxing",
        "ladbrokes_au": "boxing", "neds_au": "boxing", "kambi_multi": "boxing",
        "draftkings": "boxing",
        "coolbet": "boxing", "comeon": "boxing", "leon": "boxing", "pinnacle_guest": "boxing",
    },
    "tennis": {
        "sport": "Tennis", "league": "Tennis",
        "bovada": "tennis", "fanduel": "tennis", "betrivers": "tennis",
        "pinnacle_sport": "tennis", "kambi": "tennis",
        "smarkets": "tennis", "matchbook": "tennis",
        "ladbrokes_au": "tennis", "neds_au": "tennis", "kambi_multi": "tennis",
        "draftkings": "tennis",
        "twentytwobet": "tennis", "pointsbet": "tennis_atp",
        "pinnacle_v3": "tennis", "unibet_detail": "tennis", "paf_detail": "tennis",
        "coolbet": "tennis", "comeon": "tennis", "leon": "tennis", "pinnacle_guest": "tennis",
    },
    "golf": {
        "sport": "Golf", "league": "Golf",
        "bovada": "golf", "fanduel": "golf", "betrivers": "golf",
        "pinnacle_sport": "golf", "kambi": "golf", "matchbook": "golf",
        "ladbrokes_au": "golf", "neds_au": "golf", "kambi_multi": "golf",
        "underdog": "golf", "draftkings": "golf",
        "coolbet": "golf", "comeon": "golf", "leon": "golf", "pinnacle_guest": "golf",
    },
    "cricket": {
        "sport": "Cricket", "league": "Cricket",
        "kambi": "cricket", "smarkets": "cricket", "matchbook": "cricket",
        "ladbrokes_au": "cricket", "neds_au": "cricket", "kambi_multi": "cricket",
        "coolbet": "cricket", "comeon": "cricket", "leon": "cricket", "pinnacle_guest": "cricket",
    },
    "rugby": {
        "sport": "Rugby", "league": "Rugby Union",
        "kambi": "rugby", "smarkets": "rugby", "matchbook": "rugby",
        "ladbrokes_au": "rugby_union", "neds_au": "rugby_union", "kambi_multi": "rugby_union",
        "coolbet": "rugby_union", "comeon": "rugby_union", "leon": "rugby_union", "pinnacle_guest": "rugby_union",
    },
    "darts": {
        "sport": "Darts", "league": "Darts",
        "kambi": "darts", "smarkets": "darts", "matchbook": "darts",
        "ladbrokes_au": "darts", "neds_au": "darts", "kambi_multi": "darts",
        "coolbet": "darts", "comeon": "darts", "leon": "darts", "pinnacle_guest": "darts",
    },
    "table_tennis": {
        "sport": "Table Tennis", "league": "Table Tennis",
        "kambi": "table_tennis", "smarkets": "table_tennis",
        "ladbrokes_au": "table_tennis", "neds_au": "table_tennis", "kambi_multi": "table_tennis",
        "coolbet": "table_tennis", "comeon": "table_tennis", "leon": "table_tennis", "pinnacle_guest": "table_tennis",
    },
    "volleyball": {
        "sport": "Volleyball", "league": "Volleyball",
        "kambi": "volleyball", "smarkets": "volleyball",
        "ladbrokes_au": "volleyball", "neds_au": "volleyball", "kambi_multi": "volleyball",
        "coolbet": "volleyball", "comeon": "volleyball", "leon": "volleyball", "pinnacle_guest": "volleyball",
    },
    "handball": {
        "sport": "Handball", "league": "Handball",
        "kambi": "handball", "smarkets": "handball",
        "ladbrokes_au": "handball", "neds_au": "handball", "kambi_multi": "handball",
        "coolbet": "handball", "comeon": "handball", "leon": "handball", "pinnacle_guest": "handball",
    },
    "esports": {
        "sport": "Esports", "league": "Esports",
        "kambi": "esports", "underdog": "esports",
        "coolbet": "esports", "comeon": "esports", "leon": "esports", "pinnacle_guest": "esports",
    },
    "rugby_league": {
        "sport": "Rugby League", "league": "Rugby League",
        "kambi": "rugby_league", "smarkets": "rugby_league",
        "ladbrokes_au": "rugby_league", "neds_au": "rugby_league", "kambi_multi": "rugby_league",
        "coolbet": "rugby_league", "comeon": "rugby_league", "leon": "rugby_league", "pinnacle_guest": "rugby_league",
    },
    "aussie_rules": {
        "sport": "Australian Rules", "league": "AFL",
        "kambi": "aussie_rules",
        "ladbrokes_au": "afl", "neds_au": "afl", "kambi_multi": "afl",
        "coolbet": "aussie_rules", "comeon": "aussie_rules", "leon": "aussie_rules",
    },
    "lacrosse": {
        "sport": "Lacrosse", "league": "Lacrosse",
        "kambi": "lacrosse", "underdog": "lacrosse",
        "leon": "lacrosse",
    },
    "snooker": {
        "sport": "Snooker", "league": "Snooker",
        "kambi": "snooker", "kambi_multi": "snooker",
        "coolbet": "snooker", "comeon": "snooker", "leon": "snooker", "pinnacle_guest": "snooker",
    },
    "cycling": {
        "sport": "Cycling", "league": "Cycling",
        "kambi": "cycling", "kambi_multi": "cycling",
        "coolbet": "cycling", "comeon": "cycling", "leon": "cycling", "pinnacle_guest": "cycling",
    },
    "motor_sports": {
        "sport": "Motor Sports", "league": "Motor Sports",
        "kambi": "motor_sports", "kambi_multi": "motorsport",
        "coolbet": "motor_sports", "comeon": "motor_sports", "leon": "motor_sports", "pinnacle_guest": "motor_sports",
    },
}

ALL_SPORTSBOOKS = [
    # Direct scrapers (8 original)
    "Bovada", "FanDuel", "BetRivers", "Pinnacle",
    "Kambi/Unibet", "ESPN/DraftKings", "Smarkets", "Matchbook",
    # Kambi multi-operators (6)
    "PAF", "Svenska Spel", "ATG", "Unibet UK", "Unibet SE", "Unibet NL",
    # Australian books (2)
    "Ladbrokes AU", "Neds AU",
    # DFS & Direct (2)
    "Underdog Fantasy", "DraftKings",
    # ActionNetwork meta-source books (6 major)
    "DraftKings (AN)", "FanDuel (AN)", "BetRivers (AN)", "BetMGM",
    "bet365", "Caesars",
    # ActionNetwork additional
    "Consensus", "Opening Lines",
    # International (2)
    "22Bet", "PointsBet",
    # v7 additions (3)
    "Pinnacle v3", "Unibet (Detail)", "PAF (Detail)",
    # v8 additions (3)
    "Coolbet", "Leon.bet", "Pinnacle (Guest)",
    # v9 additions (1)
    "ComeOn",
]

SPORTSBOOK_INFO = [
    # ── Direct Scrapers ──
    {"name": "Bovada", "type": "Offshore", "region": "US (Offshore)", "description": "Major offshore sportsbook with comprehensive odds"},
    {"name": "FanDuel", "type": "US Legal", "region": "US", "description": "One of the largest US legal sportsbooks (direct API)"},
    {"name": "BetRivers", "type": "US Legal", "region": "US", "description": "Rush Street Interactive sportsbook (direct API)"},
    {"name": "Pinnacle", "type": "Sharp Book", "region": "International", "description": "Known as the sharpest book with lowest margins"},
    {"name": "Kambi/Unibet", "type": "Platform", "region": "EU/International", "description": "Kambi platform primary operator (Unibet)"},
    {"name": "ESPN/DraftKings", "type": "US Legal", "region": "US", "description": "DraftKings odds served via ESPN Core API"},
    {"name": "Smarkets", "type": "Exchange", "region": "UK/EU", "description": "Betting exchange with back/lay prices"},
    {"name": "Matchbook", "type": "Exchange", "region": "UK/EU", "description": "Betting exchange with competitive prices"},
    # ── Kambi Multi-Operators ──
    {"name": "PAF", "type": "Kambi Operator", "region": "Finland/Nordics", "description": "Finnish operator on Kambi platform"},
    {"name": "Svenska Spel", "type": "Kambi Operator", "region": "Sweden", "description": "Swedish state-owned gambling operator on Kambi"},
    {"name": "ATG", "type": "Kambi Operator", "region": "Sweden", "description": "Swedish horse racing & sports betting on Kambi"},
    {"name": "Unibet UK", "type": "Kambi Operator", "region": "UK", "description": "Unibet UK-specific odds on Kambi platform"},
    {"name": "Unibet SE", "type": "Kambi Operator", "region": "Sweden", "description": "Unibet Sweden-specific odds on Kambi"},
    {"name": "Unibet NL", "type": "Kambi Operator", "region": "Netherlands", "description": "Unibet Netherlands-specific odds on Kambi"},
    # ── Australian Books ──
    {"name": "Ladbrokes AU", "type": "Australian Book", "region": "Australia", "description": "Major Australian sportsbook on Entain platform"},
    {"name": "Neds AU", "type": "Australian Book", "region": "Australia", "description": "Australian sportsbook on Entain platform"},
    # ── DFS & Direct ──
    {"name": "Underdog Fantasy", "type": "DFS / Player Props", "region": "US", "description": "Daily fantasy sports with 7000+ player prop lines"},
    {"name": "DraftKings", "type": "US Legal", "region": "US", "description": "Direct DraftKings sportsbook API (may be geo-restricted)"},
    # ── ActionNetwork Meta-Source (major US books) ──
    {"name": "DraftKings (AN)", "type": "US Legal", "region": "US", "description": "DraftKings odds via ActionNetwork aggregation"},
    {"name": "FanDuel (AN)", "type": "US Legal", "region": "US", "description": "FanDuel odds via ActionNetwork aggregation"},
    {"name": "BetRivers (AN)", "type": "US Legal", "region": "US", "description": "BetRivers odds via ActionNetwork aggregation"},
    {"name": "BetMGM", "type": "US Legal", "region": "US", "description": "BetMGM odds via ActionNetwork — one of the Big 4 US books"},
    {"name": "bet365", "type": "International", "region": "Global", "description": "bet365 odds via ActionNetwork — world's largest online bookmaker"},
    {"name": "Caesars", "type": "US Legal", "region": "US", "description": "Caesars Sportsbook odds via ActionNetwork"},
    {"name": "Consensus", "type": "Aggregated", "region": "US", "description": "Consensus line across major US sportsbooks (ActionNetwork)"},
    {"name": "Opening Lines", "type": "Reference", "region": "US", "description": "Opening lines for comparison (ActionNetwork)"},
    # ── International Books ──
    {"name": "22Bet", "type": "International", "region": "Global", "description": "Major international sportsbook with 600+ soccer events"},
    {"name": "PointsBet", "type": "US Legal", "region": "US/AU", "description": "US/AU sportsbook with 90+ markets per event"},
    # ── v7 Additions ──
    {"name": "Pinnacle v3", "type": "Sharp Book", "region": "International", "description": "Pinnacle Arcadia API — sharp odds for NBA, Soccer, Tennis, MMA, Baseball"},
    {"name": "Unibet (Detail)", "type": "EU/International", "region": "EU/Global", "description": "Unibet via Kambi event detail — ML, spread, total for all major sports"},
    {"name": "PAF (Detail)", "type": "EU/Nordics", "region": "Finland/Nordics", "description": "PAF via Kambi event detail — ML, spread, total for all major sports"},
    # ── v8 Additions ──
    {"name": "Coolbet", "type": "EU/Nordics", "region": "Estonia/Nordics", "description": "Coolbet via Kambi CDN — full odds with betoffer detail for all sports"},
    {"name": "Leon.bet", "type": "International", "region": "Global", "description": "Major international sportsbook — 5900+ events, 39 sports, full markets"},
    {"name": "Pinnacle (Guest)", "type": "Sharp Book", "region": "International", "description": "Pinnacle Guest API — matchups + straight markets with sharp odds"},
    # ── v9 Additions ──
    {"name": "ComeOn", "type": "EU/International", "region": "EU/Global", "description": "ComeOn via Kambi CDN — full odds with betoffer detail for 17+ sports including soccer & esports"},
]


# ─── Fetching ─────────────────────────────────────────────────────────

async def _fetch_book(book_name: str, coro) -> Tuple[str, List[SportsbookSnapshot]]:
    """Wrapper to catch exceptions from individual book fetches."""
    try:
        result = await coro
        if isinstance(result, list):
            return (book_name, result)
        return (book_name, [])
    except Exception as e:
        print(f"[Aggregator] Error from {book_name}: {e}")
        return (book_name, [])


async def fetch_sport_all_books(sport_key: str) -> List[SportsbookSnapshot]:
    """Fetch odds for a sport from all sportsbooks concurrently."""
    cached = cache.get(f"sport:{sport_key}")
    if cached is not None:
        return cached

    slug_info = SPORT_SLUGS.get(sport_key, {})
    if not slug_info:
        return []

    tasks = []

    # ── Original 8 Books ──
    bovada_slug = slug_info.get("bovada")
    if bovada_slug:
        tasks.append(_fetch_book("Bovada", bovada.fetch_sport(bovada_slug)))

    fanduel_slug = slug_info.get("fanduel")
    if fanduel_slug:
        tasks.append(_fetch_book("FanDuel", fanduel.fetch_sport(fanduel_slug)))

    betrivers_slug = slug_info.get("betrivers")
    if betrivers_slug:
        tasks.append(_fetch_book("BetRivers", betrivers.fetch_sport(betrivers_slug)))

    pinnacle_league = slug_info.get("pinnacle_league")
    pinnacle_sport = slug_info.get("pinnacle_sport")
    if pinnacle_league:
        tasks.append(_fetch_book("Pinnacle", pinnacle.fetch_league(pinnacle_league)))
    elif pinnacle_sport:
        tasks.append(_fetch_book("Pinnacle", pinnacle.fetch_sport(pinnacle_sport)))

    kambi_sport = slug_info.get("kambi")
    if kambi_sport:
        tasks.append(_fetch_book("Kambi/Unibet", kambi.fetch_sport(kambi_sport)))

    espn_sport = slug_info.get("espn")
    if espn_sport:
        tasks.append(_fetch_book("ESPN/DraftKings", espn.fetch_sport(espn_sport)))

    smarkets_sport = slug_info.get("smarkets")
    if smarkets_sport:
        tasks.append(_fetch_book("Smarkets", smarkets.fetch_sport(smarkets_sport)))

    matchbook_sport = slug_info.get("matchbook")
    if matchbook_sport:
        tasks.append(_fetch_book("Matchbook", matchbook.fetch_sport(matchbook_sport)))

    # ── Kambi Multi-Operators (6 additional) ──
    kambi_multi_sport = slug_info.get("kambi_multi")
    if kambi_multi_sport:
        for op_key in kambi_multi.WORKING_OPERATORS:
            if op_key in kambi_multi.KAMBI_OPERATORS:
                _, display_name, _ = kambi_multi.KAMBI_OPERATORS[op_key]
                tasks.append(_fetch_book(
                    display_name,
                    kambi_multi.fetch_operator(op_key, kambi_multi_sport)
                ))

    # ── Australian Books ──
    ladbrokes_sport = slug_info.get("ladbrokes_au")
    if ladbrokes_sport:
        tasks.append(_fetch_book("Ladbrokes AU", ladbrokes_au.fetch_sport(ladbrokes_sport)))

    neds_sport = slug_info.get("neds_au")
    if neds_sport:
        tasks.append(_fetch_book("Neds AU", neds_au.fetch_sport(neds_sport)))

    # ── DFS / Player Props ──
    underdog_sport = slug_info.get("underdog")
    if underdog_sport:
        tasks.append(_fetch_book("Underdog Fantasy", underdog.fetch_sport(underdog_sport)))

    # ── DraftKings Direct ──
    dk_sport = slug_info.get("draftkings")
    if dk_sport:
        tasks.append(_fetch_book("DraftKings", draftkings.fetch_sport(dk_sport)))

    # ── ActionNetwork (returns multiple snapshots — one per book) ──
    an_sport = slug_info.get("actionnetwork")
    if an_sport:
        tasks.append(_fetch_book("ActionNetwork", actionnetwork.fetch_sport(an_sport)))

    # ── 22Bet ──
    tt_sport = slug_info.get("twentytwobet")
    if tt_sport:
        tasks.append(_fetch_book("22Bet", twentytwobet.fetch_sport(tt_sport)))

    # ── PointsBet ──
    pb_sport = slug_info.get("pointsbet")
    if pb_sport:
        tasks.append(_fetch_book("PointsBet", pointsbet.fetch_sport(pb_sport)))

    # ── Pinnacle v3 (Arcadia) ──
    pv3_sport = slug_info.get("pinnacle_v3")
    if pv3_sport:
        tasks.append(_fetch_book("Pinnacle v3", pinnacle_v3.fetch_sport(pv3_sport)))

    # ── Unibet (Kambi Detail) ──
    ub_sport = slug_info.get("unibet_detail")
    if ub_sport:
        tasks.append(_fetch_book("Unibet (Detail)", unibet.fetch_sport(ub_sport)))

    # ── PAF (Kambi Detail) ──
    paf_sport = slug_info.get("paf_detail")
    if paf_sport:
        tasks.append(_fetch_book("PAF (Detail)", paf.fetch_sport(paf_sport)))

    # ── Coolbet (Kambi CDN) ──
    cb_sport = slug_info.get("coolbet")
    if cb_sport:
        tasks.append(_fetch_book("Coolbet", coolbet.fetch_sport(cb_sport)))

    # ── ComeOn (Kambi CDN) ──
    co_sport = slug_info.get("comeon")
    if co_sport:
        tasks.append(_fetch_book("ComeOn", comeon.fetch_sport(co_sport)))

    # ── Leon.bet ──
    leon_sport = slug_info.get("leon")
    if leon_sport:
        tasks.append(_fetch_book("Leon.bet", leon.fetch_sport(leon_sport)))

    # ── Pinnacle (Guest) ──
    pg_sport = slug_info.get("pinnacle_guest")
    if pg_sport:
        tasks.append(_fetch_book("Pinnacle (Guest)", pinnacle_guest.fetch_sport(pg_sport)))

    # Execute all concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_snapshots = []
    for result in results:
        if isinstance(result, tuple):
            book_name, snapshots = result
            all_snapshots.extend(snapshots)
        elif isinstance(result, Exception):
            print(f"[Aggregator] Task error: {result}")

    cache.set(f"sport:{sport_key}", all_snapshots)
    return all_snapshots


async def fetch_single_book(sport_key: str, sportsbook: str) -> List[SportsbookSnapshot]:
    """Fetch odds from a single sportsbook."""
    cache_key = f"book:{sportsbook}:{sport_key}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    slug_info = SPORT_SLUGS.get(sport_key, {})
    snapshots = []

    try:
        sb = sportsbook.lower().replace("/", "").replace(" ", "")

        if sb == "bovada":
            slug = slug_info.get("bovada")
            if slug:
                snapshots = await bovada.fetch_sport(slug)
        elif sb == "fanduel":
            slug = slug_info.get("fanduel")
            if slug:
                snapshots = await fanduel.fetch_sport(slug)
        elif sb == "betrivers":
            slug = slug_info.get("betrivers")
            if slug:
                snapshots = await betrivers.fetch_sport(slug)
        elif sb == "pinnacle":
            league = slug_info.get("pinnacle_league")
            sport = slug_info.get("pinnacle_sport")
            if league:
                snapshots = await pinnacle.fetch_league(league)
            elif sport:
                snapshots = await pinnacle.fetch_sport(sport)
        elif sb in ("kambiunibet", "kambi", "unibet"):
            sport = slug_info.get("kambi")
            if sport:
                snapshots = await kambi.fetch_sport(sport)
        elif sb in ("espndraftkings", "espn"):
            sport = slug_info.get("espn")
            if sport:
                snapshots = await espn.fetch_sport(sport)
        elif sb == "smarkets":
            sport = slug_info.get("smarkets")
            if sport:
                snapshots = await smarkets.fetch_sport(sport)
        elif sb == "matchbook":
            sport = slug_info.get("matchbook")
            if sport:
                snapshots = await matchbook.fetch_sport(sport)
        # ── Kambi Multi-Operators ──
        elif sb == "paf":
            sport = slug_info.get("kambi_multi")
            if sport:
                snapshots = await kambi_multi.fetch_operator("paf", sport)
        elif sb == "svenskaspel":
            sport = slug_info.get("kambi_multi")
            if sport:
                snapshots = await kambi_multi.fetch_operator("svenskaspel", sport)
        elif sb == "atg":
            sport = slug_info.get("kambi_multi")
            if sport:
                snapshots = await kambi_multi.fetch_operator("atg", sport)
        elif sb == "unibetuk":
            sport = slug_info.get("kambi_multi")
            if sport:
                snapshots = await kambi_multi.fetch_operator("unibet_uk", sport)
        elif sb == "unibetse":
            sport = slug_info.get("kambi_multi")
            if sport:
                snapshots = await kambi_multi.fetch_operator("unibet_se", sport)
        elif sb == "unibetnl":
            sport = slug_info.get("kambi_multi")
            if sport:
                snapshots = await kambi_multi.fetch_operator("unibet_nl", sport)
        # ── Australian Books ──
        elif sb == "ladbrokesau":
            sport = slug_info.get("ladbrokes_au")
            if sport:
                snapshots = await ladbrokes_au.fetch_sport(sport)
        elif sb == "nedsau":
            sport = slug_info.get("neds_au")
            if sport:
                snapshots = await neds_au.fetch_sport(sport)
        # ── DFS ──
        elif sb in ("underdogfantasy", "underdog"):
            sport = slug_info.get("underdog")
            if sport:
                snapshots = await underdog.fetch_sport(sport)
        # ── DraftKings Direct ──
        elif sb == "draftkings":
            sport = slug_info.get("draftkings")
            if sport:
                snapshots = await draftkings.fetch_sport(sport)
        # ── ActionNetwork books ──
        elif sb in ("draftkingsan", "draftkings(an)"):
            sport = slug_info.get("actionnetwork")
            if sport:
                snap = await actionnetwork.fetch_single_book(sport, "draftkings_an")
                if snap:
                    snapshots = [snap]
        elif sb in ("fanduelan", "fanduel(an)"):
            sport = slug_info.get("actionnetwork")
            if sport:
                snap = await actionnetwork.fetch_single_book(sport, "fanduel_an")
                if snap:
                    snapshots = [snap]
        elif sb in ("betriversan", "betrivers(an)"):
            sport = slug_info.get("actionnetwork")
            if sport:
                snap = await actionnetwork.fetch_single_book(sport, "betrivers_an")
                if snap:
                    snapshots = [snap]
        elif sb == "betmgm":
            sport = slug_info.get("actionnetwork")
            if sport:
                snap = await actionnetwork.fetch_single_book(sport, "betmgm")
                if snap:
                    snapshots = [snap]
        elif sb == "bet365":
            sport = slug_info.get("actionnetwork")
            if sport:
                snap = await actionnetwork.fetch_single_book(sport, "bet365")
                if snap:
                    snapshots = [snap]
        elif sb == "caesars":
            sport = slug_info.get("actionnetwork")
            if sport:
                snap = await actionnetwork.fetch_single_book(sport, "caesars")
                if snap:
                    snapshots = [snap]
        elif sb == "consensus":
            sport = slug_info.get("actionnetwork")
            if sport:
                snap = await actionnetwork.fetch_single_book(sport, "consensus")
                if snap:
                    snapshots = [snap]
        elif sb in ("openinglines", "opening_lines"):
            sport = slug_info.get("actionnetwork")
            if sport:
                snap = await actionnetwork.fetch_single_book(sport, "opening_lines")
                if snap:
                    snapshots = [snap]
        # ── 22Bet ──
        elif sb in ("22bet", "twentytwobet"):
            sport = slug_info.get("twentytwobet")
            if sport:
                snapshots = await twentytwobet.fetch_sport(sport)
        # ── PointsBet ──
        elif sb == "pointsbet":
            sport = slug_info.get("pointsbet")
            if sport:
                snapshots = await pointsbet.fetch_sport(sport)
        # ── Pinnacle v3 ──
        elif sb in ("pinnaclev3", "pinnacle_v3"):
            sport = slug_info.get("pinnacle_v3")
            if sport:
                snapshots = await pinnacle_v3.fetch_sport(sport)
        # ── Unibet (Detail) ──
        elif sb in ("unibet(detail)", "unibetdetail", "unibet_detail"):
            sport = slug_info.get("unibet_detail")
            if sport:
                snapshots = await unibet.fetch_sport(sport)
        # ── PAF (Detail) ──
        elif sb in ("paf(detail)", "pafdetail", "paf_detail"):
            sport = slug_info.get("paf_detail")
            if sport:
                snapshots = await paf.fetch_sport(sport)
        # ── Coolbet ──
        elif sb == "coolbet":
            sport = slug_info.get("coolbet")
            if sport:
                snapshots = await coolbet.fetch_sport(sport)
        # ── ComeOn ──
        elif sb == "comeon":
            sport = slug_info.get("comeon")
            if sport:
                snapshots = await comeon.fetch_sport(sport)
        # ── Leon.bet ──
        elif sb in ("leon.bet", "leonbet", "leon"):
            sport = slug_info.get("leon")
            if sport:
                snapshots = await leon.fetch_sport(sport)
        # ── Pinnacle (Guest) ──
        elif sb in ("pinnacle(guest)", "pinnacleguest", "pinnacle_guest"):
            sport = slug_info.get("pinnacle_guest")
            if sport:
                snapshots = await pinnacle_guest.fetch_sport(sport)

    except Exception as e:
        print(f"[Aggregator] Error from {sportsbook}: {e}")

    cache.set(cache_key, snapshots)
    return snapshots


# ─── Event Matching & Comparison ──────────────────────────────────────

# Common abbreviation -> full team name mappings for cross-book matching
_ABBREV_MAP = {
    # NBA
    "atl": "atlanta", "bkn": "brooklyn", "bos": "boston", "cha": "charlotte",
    "chi": "chicago", "cle": "cleveland", "dal": "dallas", "den": "denver",
    "det": "detroit", "gsw": "golden state", "gs": "golden state",
    "hou": "houston", "ind": "indiana", "lac": "la clippers", "lal": "la lakers",
    "mem": "memphis", "mia": "miami", "mil": "milwaukee", "min": "minnesota",
    "nop": "new orleans", "no": "new orleans", "nyk": "new york", "ny": "new york",
    "okc": "oklahoma city", "orl": "orlando", "phi": "philadelphia",
    "phx": "phoenix", "por": "portland", "sac": "sacramento",
    "sas": "san antonio", "sa": "san antonio", "tor": "toronto",
    "uta": "utah", "was": "washington", "wsh": "washington",
    # NHL
    "ana": "anaheim", "ari": "arizona", "buf": "buffalo", "car": "carolina",
    "cbj": "columbus", "cgy": "calgary", "col": "colorado", "edm": "edmonton",
    "fla": "florida", "lak": "los angeles", "mtl": "montreal", "njd": "new jersey",
    "nsh": "nashville", "nyi": "ny islanders", "nyr": "ny rangers",
    "ott": "ottawa", "pit": "pittsburgh", "sea": "seattle", "sjs": "san jose",
    "stl": "st louis", "tbl": "tampa bay", "tb": "tampa bay",
    "van": "vancouver", "vgk": "vegas", "wpg": "winnipeg",
    # NFL
    "arz": "arizona", "bal": "baltimore", "cin": "cincinnati",
    "gb": "green bay", "jax": "jacksonville", "kc": "kansas city",
    "lv": "las vegas", "lar": "la rams", "lac": "la chargers",
    "ne": "new england", "nyg": "ny giants", "nyj": "ny jets",
    "sf": "san francisco", "ten": "tennessee",
    # MLB
    "chc": "chicago cubs", "chw": "chicago white sox", "cws": "chicago white sox",
    "kcr": "kansas city", "laa": "los angeles angels", "lad": "los angeles dodgers",
    "sdp": "san diego", "sd": "san diego", "tex": "texas",
    "tbr": "tampa bay",
}

def _normalize_team(name: str) -> str:
    """Normalize team name for matching across sportsbooks."""
    name = name.lower().strip()
    # Remove common prefixes
    for prefix in ["the ", "los ", "las "]:
        if name.startswith(prefix):
            name = name[len(prefix):]
    # Remove "l.a." -> "la"
    name = name.replace("l.a.", "la").replace(".", "")
    # Common name replacements
    replacements = {
        "76ers": "sixers",
        "trail blazers": "blazers",
        "timberwolves": "wolves",
    }
    for old, new in replacements.items():
        name = name.replace(old, new)
    # Expand abbreviations (e.g., "ATL Hawks" -> "atlanta hawks")
    words = name.split()
    if len(words) >= 2 and words[0] in _ABBREV_MAP:
        words[0] = _ABBREV_MAP[words[0]]
        name = " ".join(words)
    return name


def _teams_match(team1: str, team2: str) -> bool:
    """Check if two team names refer to the same team."""
    n1 = _normalize_team(team1)
    n2 = _normalize_team(team2)
    if n1 == n2:
        return True
    words1 = set(n1.split())
    words2 = set(n2.split())
    if words1 and words2:
        overlap = words1 & words2
        if overlap and (len(overlap) >= min(len(words1), len(words2))):
            return True
    return False


def _events_match(ev1: Event, ev2: Event) -> bool:
    """Check if two events from different sportsbooks are the same game."""
    home_match = _teams_match(ev1.home_team, ev2.home_team)
    away_match = _teams_match(ev1.away_team, ev2.away_team)
    if home_match and away_match:
        return True
    if _teams_match(ev1.home_team, ev2.away_team) and _teams_match(ev1.away_team, ev2.home_team):
        return True
    if ev1.start_time and ev2.start_time:
        time_diff = abs((ev1.start_time - ev2.start_time).total_seconds())
        if time_diff < 7200:
            if home_match or away_match:
                return True
    return False


def aggregate_events(snapshots: List[SportsbookSnapshot]) -> List[AggregatedEvent]:
    """Match events across sportsbooks and aggregate."""
    aggregated: List[AggregatedEvent] = []
    all_events: List[Tuple[str, Event]] = []
    for snap in snapshots:
        for ev in snap.events:
            all_events.append((snap.sportsbook, ev))

    matched_indices = set()
    for i, (book1, ev1) in enumerate(all_events):
        if i in matched_indices:
            continue
        agg = AggregatedEvent(
            home_team=ev1.home_team,
            away_team=ev1.away_team,
            sport=ev1.sport,
            league=ev1.league,
            start_time=ev1.start_time,
            is_live=ev1.is_live,
            sportsbook_odds={book1: ev1},
        )
        matched_indices.add(i)
        for j, (book2, ev2) in enumerate(all_events):
            if j in matched_indices:
                continue
            if book2 == book1:
                continue
            if _events_match(ev1, ev2):
                agg.sportsbook_odds[book2] = ev2
                matched_indices.add(j)
                if ev2.is_live:
                    agg.is_live = True
        aggregated.append(agg)
    return aggregated


def find_best_odds(aggregated: List[AggregatedEvent]) -> List[BestOdds]:
    """Find the best odds across all sportsbooks for each event."""
    results = []
    for agg in aggregated:
        best_markets: Dict[str, Dict[str, Tuple[int, str]]] = {}
        for book_name, event in agg.sportsbook_odds.items():
            for market in event.markets:
                mkey = market.market_type.value
                if mkey not in best_markets:
                    best_markets[mkey] = {}
                for outcome in market.outcomes:
                    okey = outcome.name
                    if outcome.price_american is not None:
                        current = best_markets[mkey].get(okey)
                        if current is None or outcome.price_american > current[0]:
                            best_markets[mkey][okey] = (outcome.price_american, book_name)
        if best_markets:
            results.append(BestOdds(event=agg, best_prices=best_markets))
    return results


# ─── Available Sports ─────────────────────────────────────────────────

def get_available_sports() -> List[dict]:
    """Return list of available sports with sportsbook coverage."""
    sports = []
    for key, info in SPORT_SLUGS.items():
        books = []
        if info.get("bovada"): books.append("Bovada")
        if info.get("fanduel"): books.append("FanDuel")
        if info.get("betrivers"): books.append("BetRivers")
        if info.get("pinnacle_league") or info.get("pinnacle_sport"): books.append("Pinnacle")
        if info.get("kambi"): books.append("Kambi/Unibet")
        if info.get("espn"): books.append("ESPN/DraftKings")
        if info.get("smarkets"): books.append("Smarkets")
        if info.get("matchbook"): books.append("Matchbook")
        if info.get("kambi_multi"):
            books.extend(["PAF", "Svenska Spel", "ATG", "Unibet UK", "Unibet SE", "Unibet NL"])
        if info.get("ladbrokes_au"): books.append("Ladbrokes AU")
        if info.get("neds_au"): books.append("Neds AU")
        if info.get("underdog"): books.append("Underdog Fantasy")
        if info.get("draftkings"): books.append("DraftKings")
        if info.get("actionnetwork"):
            books.extend(["DraftKings (AN)", "FanDuel (AN)", "BetRivers (AN)",
                         "BetMGM", "bet365", "Caesars", "Consensus", "Opening Lines"])
        if info.get("twentytwobet"): books.append("22Bet")
        if info.get("pointsbet"): books.append("PointsBet")
        if info.get("pinnacle_v3"): books.append("Pinnacle v3")
        if info.get("unibet_detail"): books.append("Unibet (Detail)")
        if info.get("paf_detail"): books.append("PAF (Detail)")
        sports.append({
            "key": key,
            "sport": info["sport"],
            "league": info["league"],
            "sportsbooks": books,
            "sportsbook_count": len(books),
        })
    return sports
