"""Regression test for the 'columnar pods leaking empty team names' bug
hit in production after PR #6 v1 deploy.

We construct a synthetic homepage-pods blob mirroring exactly what
production was emitting (fixture-PAs without a CL marker, then
selection-style MAs with CL=18 + OD), and assert the parser now
returns proper team names.
"""
import sys
import os
# Walk up from scripts/tests/ → scripts/ → sb-api/ to import scrapers
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _ROOT)

from scrapers import bet365


def make_record(rtype, **fields):
    parts = [f"{rtype};"]
    for k, v in fields.items():
        parts.append(f"{k}={v};")
    return "".join(parts)


# Synthetic blob: structure mirrors what nj.bet365.com homepage pods
# return. Fixture-PAs come FIRST (with NA=home, N2=away, FI=ID)
# *without* any preceding CL/EV marker — this is the production bug
# that left teams blank.
records = [
    # Two fixture-PAs (no CL anchoring — bug case)
    make_record("PA", FI="194832551", NA="NY Knicks", N2="CLE Cavaliers",
                FD="NY Knicks v CLE Cavaliers", BC="20260524000000"),
    make_record("PA", FI="194832552", NA="LA Lakers", N2="GS Warriors",
                FD="LA Lakers v GS Warriors", BC="20260524023000"),
    # Selection-style MAs with CL=18 + OD set (this is what production
    # was producing, hitting the line-421 MA-OD branch).
    make_record("MA", CL="18", FI="194832551", NA="NY Knicks", OD="6/5",
                MN="Money Line: NY Knicks"),
    make_record("MA", CL="18", FI="194832551", NA="CLE Cavaliers", OD="5/7",
                MN="Money Line: CLE Cavaliers"),
    make_record("MA", CL="18", FI="194832552", NA="LA Lakers", OD="11/10",
                MN="Money Line: LA Lakers"),
    make_record("MA", CL="18", FI="194832552", NA="GS Warriors", OD="10/11",
                MN="Money Line: GS Warriors"),
]

blob = "|".join(records)

# Parse + build
parsed = bet365._parse_blob(blob)
print(f"parsed records: {len(parsed)}")
for r in parsed:
    print(f"  {r[0]}: {dict(list(r[1].items())[:3])}...")

events = bet365._build_events_from_records(parsed, sport="nba", target_cl=18)
print(f"\nevents: {len(events)}")
for e in events:
    print(f"  {e.event_id}: home={e.home_team!r} away={e.away_team!r} "
          f"start={e.start_time} markets={[(m.name, len(m.outcomes)) for m in e.markets]}")

assert len(events) == 2, f"expected 2 events, got {len(events)}"

ev1 = next(e for e in events if e.event_id == "194832551")
assert ev1.home_team == "NY Knicks", f"home_team should be 'NY Knicks', got {ev1.home_team!r}"
assert ev1.away_team == "CLE Cavaliers", f"away_team should be 'CLE Cavaliers', got {ev1.away_team!r}"
assert ev1.start_time is not None, f"start_time must be parsed, got {ev1.start_time}"

ev2 = next(e for e in events if e.event_id == "194832552")
assert ev2.home_team == "LA Lakers"
assert ev2.away_team == "GS Warriors"

# Each event should have at least one moneyline-ish market with 2 outcomes
for ev in (ev1, ev2):
    total_outcomes = sum(len(m.outcomes) for m in ev.markets)
    assert total_outcomes >= 2, f"{ev.event_id} should have >= 2 outcomes, got {total_outcomes}"
    # MN-suffix stripping: both MLs should merge into a single "Money Line" market
    ml_markets = [m for m in ev.markets if m.name == "Money Line"]
    assert len(ml_markets) == 1, (
        f"{ev.event_id}: expected exactly 1 'Money Line' market, "
        f"got {len(ml_markets)}: {[m.name for m in ev.markets]}"
    )
    assert len(ml_markets[0].outcomes) == 2, (
        f"{ev.event_id}: Money Line should have 2 outcomes, "
        f"got {len(ml_markets[0].outcomes)}"
    )

print("\nALL REGRESSION CHECKS PASSED")

# ─── Additional: classic EV-context shape still works ───
print("\n--- Verifying classic EV-context shape (regression guard) ---")
ev_records = [
    make_record("CL", ID="18", NA="Basketball"),
    make_record("EV", ID="200000001", CL="18", NA="Boston Celtics v Miami Heat",
                TT="20260601000000", L3="NBA Playoffs"),
    make_record("MA", MA="1", NA="Match Winner"),
    make_record("PA", FI="200000001", NA="Boston Celtics", OD="4/5"),
    make_record("PA", FI="200000001", NA="Miami Heat", OD="11/10"),
]
blob2 = "|".join(ev_records)
parsed2 = bet365._parse_blob(blob2)
events2 = bet365._build_events_from_records(parsed2, sport="nba", target_cl=18)
print(f"events: {len(events2)}")
assert len(events2) == 1
e = events2[0]
print(f"  {e.event_id}: home={e.home_team!r} away={e.away_team!r}")
assert e.home_team == "Boston Celtics", f"got {e.home_team!r}"
assert e.away_team == "Miami Heat", f"got {e.away_team!r}"
print("  EV-context shape: OK")

print("\nALL TESTS PASSED ✓")

# ─── Additional: NA-only "Market: Selection" (no MN field) shape ───
# This is the production shape that PR #7 v1 missed: MA records have
# the full label in NA with no MN, AND the FI has no fixture-PA at all.
# We expect the parser to (a) split NA into market/selection, and
# (b) recover home/away from the ML outcomes via post-processing.
print("\n--- Verifying NA-only label + ML team recovery ---")
na_only = [
    # No fixture-PA at all for FI=300000001 (orphan pod tile)
    make_record("MA", CL="18", FI="300000001", NA="Money Line: NY Knicks", OD="6/5"),
    make_record("MA", CL="18", FI="300000001", NA="Money Line: CLE Cavaliers", OD="5/7"),
]
blob3 = "|".join(na_only)
parsed3 = bet365._parse_blob(blob3)
events3 = bet365._build_events_from_records(parsed3, sport="nba", target_cl=18)
print(f"events: {len(events3)}")
assert len(events3) == 1
e3 = events3[0]
print(f"  {e3.event_id}: home={e3.home_team!r} away={e3.away_team!r} markets={[(m.name, len(m.outcomes)) for m in e3.markets]}")
assert e3.home_team in ("CLE Cavaliers", "NY Knicks"), f"home_team should be recovered, got {e3.home_team!r}"
assert e3.away_team in ("CLE Cavaliers", "NY Knicks"), f"away_team should be recovered, got {e3.away_team!r}"
assert e3.home_team != e3.away_team
ml_markets = [m for m in e3.markets if m.name == "Money Line"]
assert len(ml_markets) == 1, f"expected single 'Money Line' market, got {[m.name for m in e3.markets]}"
assert len(ml_markets[0].outcomes) == 2
labels = sorted(o.name for o in ml_markets[0].outcomes)
assert labels == ["CLE Cavaliers", "NY Knicks"], f"outcome labels should be team names, got {labels}"
print("  NA-only + ML team recovery: OK")

print("\n*** ALL 3 TEST CASES PASSED ***")
