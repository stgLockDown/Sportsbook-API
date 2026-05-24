"""
Unit-style test for scrapers/aggregator.py per-sport league filter.

Validates the _league_matches_sport() predicate against a curated table
of real-world strings observed in production scraper output. Mirrors the
style of check_b365_columnar_pods.py.

Run with: python -m scripts.tests.check_aggregator_league_filter
"""
import sys
from pathlib import Path

# Make the package importable when run as a script.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapers.aggregator import (  # noqa: E402
    _league_matches_sport,
    _word_boundary_match,
    SPORT_LEAGUE_FILTERS,
)


# ─── Word-boundary primitive ───────────────────────────────────────────────
WB_CASES = [
    # (haystack, needle, expected)
    ("nba",                 "nba",  True),
    ("WNBA",                "nba",  False),   # alpha-neighbor on left
    ("nbl",                 "nba",  False),
    ("ncaab",               "ncaa", False),   # alpha-neighbor on right (b)
    ("NCAAB",               "ncaab", True),
    ("Hockey/AHL",          "nhl",  False),
    ("nhl",                 "nhl",  True),
    ("ICE_HOCKEY_NHL",      "nhl",  True),    # underscore is non-alnum
    ("Ice Hockey NHL",      "nhl",  True),
    ("Football/NCAAF",      "nfl",  False),
    ("Football/NFL",        "nfl",  True),
    ("USA. UAHL",           "ahl",  False),   # 'ahl' inside 'UAHL' is alpha-bounded → no match
    ("Hockey/AHL",          "ahl",  True),    # '/' is non-alnum on both sides → match
    ("NBA Eastern Conf.",   "nba",  True),
    ("NBA-Eastern",         "nba",  True),
    ("",                    "nba",  False),
    ("nba",                 "",     False),
]


# ─── Real-world league strings observed in /events/{sport} responses ──────
# Each row: (league, sport_key, home, away, expected, note)
LEAGUE_CASES = [
    # ── NHL: should ACCEPT only real NHL ──────────────────────────────
    ("NHL",                          "nhl", "Vegas Golden Knights", "Colorado Avalanche", True,  "real NHL"),
    ("ICE_HOCKEY_NHL",               "nhl", "VGK", "COL",                            True,  "DK-style key"),
    ("Hockey/AHL",                   "nhl", "Cleveland Monsters", "Toronto Marlies",  False, "AHL leak"),
    ("Hockey/World Championship",    "nhl", "Denmark", "Italy",                      False, "IIHF leak"),
    ("IIHF World Championship. 2026","nhl", "Norway", "Czech Republic",              False, "IIHF leak"),
    ("RHL",                          "nhl", "Phoenix Tula", "Berkut Volgograd",      False, "Russian league"),
    ("Australia. AIHL",              "nhl", "Perth Thunder", "Melbourne Ice",        False, "Australian league"),
    ("USA. UAHL",                    "nhl", "Stalnye Topory", "Metkie Strelki",      False, "UAHL leak"),
    ("Tournament Magnitka Open",     "nhl", "Hitrye Lisy", "Svirepye Eji",           False, "Russian club"),
    ("Dream League",                 "nhl", "Botany Swarm", "Canterbury Red Devils", False, "Dream League"),
    ("Hockey",                       "nhl", "Vegas Golden Knights", "Avalanche",     True,  "generic + NHL teams ok"),
    # ── NBA: WNBA / NBL pollution ─────────────────────────────────────
    ("NBA",                          "nba", "Knicks", "Heat",            True,  "real NBA"),
    ("BASKETBALL_NBA",               "nba", "LAL", "BOS",                True,  "DK-style key"),
    ("WNBA",                         "nba", "Sparks", "Aces",            False, "WNBA explicit"),
    ("Australia. NBL1",              "nba", "Adelaide", "Sydney",        False, "NBL1 leak"),
    ("Australia. NBL1. Women",       "nba", "Bendigo", "Sydney",         False, "NBL1 women leak"),
    ("Spain. Liga ACB",              "nba", "Real Madrid", "Barcelona",  False, "Liga ACB leak"),
    ("Basketball",                   "nba", "Knicks", "Heat",            True,  "generic + NBA teams ok"),
    ("Basketball",                   "nba", "LA Sparks", "LV Aces",      False, "generic + WNBA team markers"),
    # ── WNBA: should ACCEPT only WNBA ─────────────────────────────────
    ("WNBA",                         "wnba", "Sparks", "Aces",           True,  "real WNBA"),
    ("BASKETBALL_WNBA",              "wnba", "NYL", "MIN",               True,  "DK-style key"),
    ("Basketball",                   "wnba", "Sparks", "Aces",           True,  "generic ok for WNBA"),
    # ── NFL: NCAAF / CFL pollution ────────────────────────────────────
    ("NFL",                          "nfl", "Patriots", "Bills",         True,  "real NFL"),
    ("Football/NFL",                 "nfl", "Patriots", "Bills",         True,  "Pinnacle-style label"),
    ("Football/NCAAF",               "nfl", "Auburn", "Alabama",         False, "NCAAF leak"),
    ("Football/CFL",                 "nfl", "Argonauts", "Stampeders",   False, "CFL leak"),
    ("NFL Regular Season Wins",      "nfl", "Patriots", "—",             False, "futures market"),
    ("NFL - To Make The Playoffs",   "nfl", "Patriots", "—",             False, "futures market"),
    ("NFL Divisions",                "nfl", "AFC East", "—",             False, "futures market"),
    # ── NCAAB / NCAAF: collegiate sanity ──────────────────────────────
    ("NCAAB",                        "ncaab","Duke", "UNC",              True,  "real NCAAB"),
    ("NCAAF",                        "ncaaf","Auburn", "Alabama",        True,  "real NCAAF"),
    ("NBA",                          "ncaab","Knicks", "Heat",           False, "NBA in NCAAB is leak"),
    # ── MLB: NPB / MiLB pollution ─────────────────────────────────────
    ("MLB",                          "mlb",  "Yankees", "Red Sox",       True,  "real MLB"),
    ("Baseball/MLB",                 "mlb",  "Yankees", "Red Sox",       True,  "Pinnacle-style label"),
    ("Japan/NPB",                    "mlb",  "Hanshin", "Yomiuri",       False, "NPB leak"),
    ("Japan. NPB",                   "mlb",  "Hanshin", "Yomiuri",       False, "NPB leak (alt sep)"),
    ("USA/Minor League Baseball",    "mlb",  "Durham", "Toledo",         False, "MiLB leak"),
    # ── Soccer: should be permissive (every league is real) ───────────
    ("Soccer/Premier League",        "soccer","Arsenal", "Chelsea",      True,  "EPL"),
    ("Soccer/La Liga",               "soccer","Real Madrid", "Barcelona",True,  "La Liga"),
    ("Football/Champions League",    "soccer","PSG", "Bayern",           True,  "EU football=soccer"),
    ("Football/NCAAF",               "soccer","Auburn", "Alabama",       False, "American football reject"),
    ("NFL",                          "soccer","Patriots", "Bills",       False, "NFL reject"),
]


def run_word_boundary() -> int:
    fails = 0
    for hay, needle, want in WB_CASES:
        got = _word_boundary_match(hay, needle)
        if got != want:
            fails += 1
            print(f"  FAIL  WB({hay!r}, {needle!r}) → {got}, want {want}")
    if not fails:
        print(f"  OK    {len(WB_CASES)} word-boundary cases")
    return fails


def run_league_matches() -> int:
    fails = 0
    for league, sport, home, away, want, note in LEAGUE_CASES:
        got = _league_matches_sport(league, sport, home=home, away=away)
        if got != want:
            fails += 1
            verdict = "ACCEPT" if got else "REJECT"
            wanted  = "ACCEPT" if want else "REJECT"
            print(f"  FAIL  [{sport}] league={league!r} home={home!r} away={away!r}")
            print(f"        got {verdict}, want {wanted}  ({note})")
    if not fails:
        print(f"  OK    {len(LEAGUE_CASES)} league-match cases")
    return fails


def main() -> int:
    print(f"SPORT_LEAGUE_FILTERS configured for: {sorted(SPORT_LEAGUE_FILTERS.keys())}")
    print()
    print("Word-boundary primitive:")
    f1 = run_word_boundary()
    print()
    print("League-match predicate:")
    f2 = run_league_matches()
    print()
    total = f1 + f2
    if total == 0:
        print("✅ All checks passed.")
        return 0
    print(f"❌ {total} check(s) failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
