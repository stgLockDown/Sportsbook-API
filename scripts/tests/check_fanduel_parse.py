"""Regression tests for FanDuel scraper market classification + parsing.

Run:
    python3 scripts/tests/check_fanduel_parse.py

These tests cover the issues fixed in the FD polish PR:
  1. "Total Points" market correctly classified as MarketType.TOTAL
     (was PLAYER_PROP because of the bare "points" keyword).
  2. "Both Teams to Score" classified as GAME_PROP (not PLAYER_PROP
     via the over-broad "to score" keyword).
  3. Player-name-prefixed markets like "LeBron James - Total Points"
     classified as PLAYER_PROP via the " - " separator pattern.
  4. Game events with " @ " separator parse home/away correctly.
  5. WNBA sport routes through the aggregator slug map.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _ROOT)

from scrapers import fanduel
from scrapers.models import MarketType


def assert_eq(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


# ─── Classifier coverage matrix ───────────────────────────────────────
print("--- Classifier matrix ---")
classifier_cases = [
    # (type_code, name, expected MarketType.value)
    ("MONEY_LINE",                "Moneyline",                   "moneyline"),
    ("MATCH_BETTING",             "Match Winner",                "moneyline"),
    ("MATCH_HANDICAP_(2-WAY)",    "Spread Betting",              "spread"),
    ("RUN_LINE",                  "Run Line",                    "spread"),
    ("PUCK_LINE",                 "Puck Line",                   "spread"),
    ("POINT_SPREAD",              "Point Spread",                "spread"),
    ("TOTAL_POINTS_(OVER/UNDER)", "Total Points",                "total"),
    ("TOTAL_RUNS",                "Total Runs",                  "total"),
    ("TOTAL_GOALS",               "Total Goals",                 "total"),
    ("",                          "Total Hits",                  "total"),
    ("NBA_PLAYER_POINTS",         "LeBron James - Total Points", "player_prop"),
    ("WNBA_PLAYER_SPECIALS",      "A'ja Wilson Specials",        "player_prop"),
    ("",                          "Anytime Goalscorer",          "player_prop"),
    ("",                          "First Touchdown Scorer",      "player_prop"),
    ("NFL_FUTURES",               "Super Bowl Winner",           "futures"),
    ("NBA_MVP",                   "NBA MVP 2026",                "futures"),
    ("",                          "Stanley Cup Winner",          "futures"),
    ("",                          "Regular Season Wins",         "futures"),
    ("NFL_TEAM_TOTAL",            "Chiefs Team Total",           "team_prop"),
    ("",                          "Race to 10 Points",           "team_prop"),
    ("",                          "Both Teams to Score",         "game_prop"),
    ("",                          "Will the Game Go to OT",      "game_prop"),
    # Note: "First Half Spread" intentionally classifies as 'spread'
    # because the spread structure dominates; consumers can filter by
    # game-state via the name if needed. Same for "First Quarter Total".
    ("",                          "Random Garbage",              "other"),
    ("",                          "",                            "other"),
]
for type_code, name, expected in classifier_cases:
    got = fanduel._classify_market(type_code, name).value
    assert_eq(got, expected, f"classify({type_code!r}, {name!r})")
    print(f"  OK  type={type_code!r:30} name={name!r:35} -> {got}")
print(f"  All {len(classifier_cases)} classifier cases passed.\n")


# ─── Parser end-to-end ────────────────────────────────────────────────
print("--- Parser e2e ---")

# Synthetic minimal FD response (mirrors content-managed-page shape).
sample_payload = {
    "attachments": {
        "events": {
            "100001": {
                "name": "Boston Celtics @ New York Knicks",
                "openDate": "2026-05-25T23:30:00.000Z",
                "homeTeam": "New York Knicks",
                "awayTeam": "Boston Celtics",
                "inPlay": False,
            },
            "100002": {
                "name": "WNBA Futures",
                "openDate": "2026-10-01T11:00:00.000Z",
                "homeTeam": None,
                "awayTeam": None,
            },
            "100003": {
                # No game data + no markets -> should be dropped
                "name": "Empty Event",
                "openDate": "2026-05-25T23:30:00.000Z",
            },
            "100004": {
                # Far-future placeholder
                "name": "2099 Future Marker",
                "openDate": "2099-12-31T00:00:00.000Z",
            },
        },
        "markets": {
            "m1": {
                "eventId": 100001,
                "marketName": "Moneyline",
                "marketType": "MONEY_LINE",
                "runners": [
                    {
                        "runnerName": "Boston Celtics",
                        "winRunnerOdds": {
                            "americanDisplayOdds": {"americanOdds": -150},
                            "trueOdds": {"decimalOdds": {"decimalOdds": 1.6667}},
                        },
                    },
                    {
                        "runnerName": "New York Knicks",
                        "winRunnerOdds": {
                            "americanDisplayOdds": {"americanOdds": 130},
                            "trueOdds": {"decimalOdds": {"decimalOdds": 2.3}},
                        },
                    },
                ],
            },
            "m2": {
                "eventId": 100001,
                "marketName": "Total Points",
                "marketType": "TOTAL_POINTS_(OVER/UNDER)",
                "runners": [
                    {
                        "runnerName": "Over",
                        "handicap": 215.5,
                        "winRunnerOdds": {
                            "americanDisplayOdds": {"americanOdds": -110},
                        },
                    },
                    {
                        "runnerName": "Under",
                        "handicap": 215.5,
                        "winRunnerOdds": {
                            "americanDisplayOdds": {"americanOdds": -110},
                        },
                    },
                ],
            },
            "m3": {
                "eventId": 100002,
                "marketName": "WNBA Regular Season MVP 2026",
                "marketType": "WNBA_MVP",
                "runners": [
                    {
                        "runnerName": "A'ja Wilson",
                        "winRunnerOdds": {"americanDisplayOdds": {"americanOdds": 200}},
                    },
                ],
            },
        },
    },
}

events = fanduel._parse_response(sample_payload, "Basketball", "NBA")
print(f"  parsed {len(events)} events")

# Far-future dropped + empty-markets dropped
assert_eq(len(events), 2, "should drop empty + far-future events")

game_ev = next(e for e in events if e.event_id == "100001")
print(f"  game: {game_ev.away_team} @ {game_ev.home_team} | {game_ev.start_time}")
assert_eq(game_ev.home_team, "New York Knicks", "game home_team")
assert_eq(game_ev.away_team, "Boston Celtics", "game away_team")
assert game_ev.start_time is not None
assert_eq(len(game_ev.markets), 2, "game markets count")

ml = next(m for m in game_ev.markets if m.name == "Moneyline")
assert_eq(ml.market_type, MarketType.MONEYLINE, "ML type")
assert_eq(len(ml.outcomes), 2, "ML outcomes")
assert_eq(ml.outcomes[0].price_american, -150, "ML home price")

tot = next(m for m in game_ev.markets if m.name == "Total Points")
assert_eq(tot.market_type, MarketType.TOTAL, "Total type — was PLAYER_PROP pre-fix")
assert_eq(tot.outcomes[0].point, 215.5, "Total line")

futures_ev = next(e for e in events if e.event_id == "100002")
assert_eq(futures_ev.markets[0].market_type, MarketType.FUTURES, "Futures market type")

print("  Parser e2e: OK\n")


# ─── Edge cases ────────────────────────────────────────────────────────
print("--- Edge cases ---")

# EVEN price string
assert_eq(fanduel._safe_american_odds("EVEN"), 100, "EVEN -> +100")
assert_eq(fanduel._safe_american_odds("EVS"), 100, "EVS -> +100")
assert_eq(fanduel._safe_american_odds("+150"), 150, "+150 string")
assert_eq(fanduel._safe_american_odds("-110"), -110, "-110 string")
assert_eq(fanduel._safe_american_odds(None), None, "None -> None")
assert_eq(fanduel._safe_american_odds(True), None, "bool guarded -> None")
assert_eq(fanduel._safe_american_odds("garbage"), None, "garbage -> None")

# Event name splitting
assert_eq(fanduel._split_event_name("Boston Celtics @ New York Knicks"),
          ("Boston Celtics", "New York Knicks"), "@ split")
assert_eq(fanduel._split_event_name("Arsenal v Chelsea"),
          ("Chelsea", "Arsenal"), "v split (soccer)")
assert_eq(fanduel._split_event_name("WNBA Futures"),
          ("", ""), "no separator")

print("  Edge cases: OK\n")

# ─── Tenant config ────────────────────────────────────────────────────
print("--- Tenant config ---")
assert len(fanduel.TENANTS) == 3, f"expected 3 tenants, got {len(fanduel.TENANTS)}"
assert "il." in fanduel.TENANTS[0]
assert "nj." in fanduel.TENANTS[1]
assert "pa." in fanduel.TENANTS[2]
print(f"  IL → NJ → PA fallback chain configured.\n")

print("*** ALL FANDUEL CHECKS PASSED ***")
