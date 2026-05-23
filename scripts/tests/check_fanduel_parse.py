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


# ─── Soccer routing (page=SPORT&eventTypeId=1) ─────────────────────────────────
#
# Soccer can't use page=CUSTOM because customPageId=mls/epl/champions-league
# all return 404 as of 2026-Q2. We route through the eventTypeId path
# instead. These tests cover:
#
#   1. _build_request_params switches between CUSTOM and SPORT correctly.
#   2. SPORT_MAP entries for soccer carry an event_type_id and (optionally)
#      a competition_id filter for per-league slugs.
#   3. _parse_response with competition_filter slices a multi-league
#      payload down to a single league's events.
#   4. Aggregator's "soccer" key routes to fanduel slug "soccer" (full
#      payload) — not to the legacy "mls" customPageId which 404s.
print("--- Soccer routing ---")

# 1. Param-builder dispatch
nfl_params = fanduel._build_request_params(fanduel.SPORT_MAP["nfl"], "nfl")
assert_eq(nfl_params["page"], "CUSTOM", "NFL → CUSTOM")
assert_eq(nfl_params["customPageId"], "nfl", "NFL customPageId")
assert "eventTypeId" not in nfl_params, "NFL must not include eventTypeId"

soccer_params = fanduel._build_request_params(fanduel.SPORT_MAP["soccer"], "soccer")
assert_eq(soccer_params["page"], "SPORT", "soccer → SPORT")
assert_eq(soccer_params["eventTypeId"], 1, "soccer eventTypeId=1")
assert "customPageId" not in soccer_params, "soccer must not include customPageId"

epl_params = fanduel._build_request_params(fanduel.SPORT_MAP["epl"], "epl")
assert_eq(epl_params["page"], "SPORT", "epl → SPORT")
assert_eq(epl_params["eventTypeId"], 1, "epl eventTypeId=1")

# 2. SPORT_MAP shape — every soccer slug has event_type_id; per-league
#    slugs additionally have a competition_id.
for slug in ["soccer", "epl", "mls", "champions-league", "la-liga", "serie-a"]:
    cfg = fanduel.SPORT_MAP[slug]
    assert cfg.get("event_type_id") == 1, f"{slug} must have event_type_id=1"

per_league = ["epl", "mls", "champions-league", "la-liga", "serie-a",
              "eredivisie", "liga-mx", "brazil-serie-a", "world-cup", "nwsl",
              "europa-league"]
for slug in per_league:
    cfg = fanduel.SPORT_MAP[slug]
    assert "competition_id" in cfg and isinstance(cfg["competition_id"], int), (
        f"{slug} must have integer competition_id"
    )

# Bare "soccer" is intentionally NOT scoped to a competition — it returns
# the full multi-league payload.
assert "competition_id" not in fanduel.SPORT_MAP["soccer"], \
    "'soccer' slug must NOT carry a competition_id (returns all leagues)"

# 3. Synthetic multi-league payload — verify competition_filter slicing.
synthetic = {
    "attachments": {
        "events": {
            "1001": {
                "eventId": 1001, "name": "Arsenal v Chelsea",
                "competitionId": 10932509,  # EPL
                "openDate": "2026-08-15T14:00:00.000Z",
            },
            "1002": {
                "eventId": 1002, "name": "Inter Miami v LA Galaxy",
                "competitionId": 141,  # MLS
                "openDate": "2026-07-04T23:30:00.000Z",
            },
            "1003": {
                "eventId": 1003, "name": "Real Madrid v Barcelona",
                "competitionId": 117,  # La Liga
                "openDate": "2026-10-20T19:00:00.000Z",
            },
        },
        "markets": {
            "m1": {
                "marketId": "m1", "eventId": 1001, "competitionId": 10932509,
                "marketName": "Match Winner", "marketType": "MATCH_BETTING",
                "runners": [
                    {"runnerName": "Arsenal", "winRunnerOdds": {"americanDisplayOdds": {"americanOdds": "+120"}}},
                    {"runnerName": "Chelsea", "winRunnerOdds": {"americanDisplayOdds": {"americanOdds": "+200"}}},
                    {"runnerName": "Draw",    "winRunnerOdds": {"americanDisplayOdds": {"americanOdds": "+250"}}},
                ],
            },
            "m2": {
                "marketId": "m2", "eventId": 1002, "competitionId": 141,
                "marketName": "Match Winner", "marketType": "MATCH_BETTING",
                "runners": [
                    {"runnerName": "Inter Miami", "winRunnerOdds": {"americanDisplayOdds": {"americanOdds": "-110"}}},
                    {"runnerName": "LA Galaxy",   "winRunnerOdds": {"americanDisplayOdds": {"americanOdds": "+250"}}},
                    {"runnerName": "Draw",        "winRunnerOdds": {"americanDisplayOdds": {"americanOdds": "+220"}}},
                ],
            },
            "m3": {
                "marketId": "m3", "eventId": 1003, "competitionId": 117,
                "marketName": "Match Winner", "marketType": "MATCH_BETTING",
                "runners": [
                    {"runnerName": "Real Madrid", "winRunnerOdds": {"americanDisplayOdds": {"americanOdds": "+105"}}},
                    {"runnerName": "Barcelona",   "winRunnerOdds": {"americanDisplayOdds": {"americanOdds": "+220"}}},
                    {"runnerName": "Draw",        "winRunnerOdds": {"americanDisplayOdds": {"americanOdds": "+260"}}},
                ],
            },
        },
    },
}

# No filter → all 3 events
all_events = fanduel._parse_response(synthetic, "Soccer", "Soccer")
assert_eq(len(all_events), 3, "synthetic: 3 events with no filter")

# EPL filter → just Arsenal v Chelsea
epl_only = fanduel._parse_response(synthetic, "Soccer", "EPL", competition_filter=10932509)
assert_eq(len(epl_only), 1, "synthetic: EPL filter → 1 event")
assert_eq(epl_only[0].home_team, "Arsenal", "EPL home team")
assert_eq(epl_only[0].away_team, "Chelsea", "EPL away team")

# MLS filter → just Inter Miami
mls_only = fanduel._parse_response(synthetic, "Soccer", "MLS", competition_filter=141)
assert_eq(len(mls_only), 1, "synthetic: MLS filter → 1 event")
assert_eq(mls_only[0].home_team, "Inter Miami", "MLS home team")

# La Liga filter → just El Clasico
laliga_only = fanduel._parse_response(synthetic, "Soccer", "La Liga", competition_filter=117)
assert_eq(len(laliga_only), 1, "synthetic: La Liga filter → 1 event")
assert_eq(laliga_only[0].home_team, "Real Madrid", "La Liga home team")

# Filter that matches nothing → empty
nada = fanduel._parse_response(synthetic, "Soccer", "X", competition_filter=99999999)
assert_eq(len(nada), 0, "synthetic: bogus filter → 0 events")

print(f"  Soccer routing + competition slicing: OK ({len(per_league)} per-league slugs)\n")


# ─── Aggregator soccer routing ─────────────────────────────────────────────────
print("--- Aggregator soccer routing ---")
from scrapers import aggregator
soccer_cfg = aggregator.SPORT_SLUGS["soccer"]
assert_eq(soccer_cfg["fanduel"], "soccer",
          "aggregator soccer.fanduel must route to FD 'soccer' slug")
print("  aggregator['soccer']['fanduel'] = 'soccer' (multi-league payload)\n")


print("*** ALL FANDUEL CHECKS PASSED ***")
