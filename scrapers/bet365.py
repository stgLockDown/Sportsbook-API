"""
bet365 scraper \u2014 Cloudflare-bypass via Playwright cookie priming.

bet365's public sportsbook (`nj.bet365.com`) is fronted by Cloudflare Bot
Management which 403s direct httpx/curl_cffi calls regardless of TLS
impersonation or proxy.

Strategy (mirrors DraftKings):
  1. A background task (`_b365_session`) primes a real Chromium browser
     every 5 min through Decodo US-RCN, harvesting the Cloudflare
     `__cf_bm` cookie plus bet365's `pstk`/`swt`/`aps03`/`rmbs` session
     cookies.
  2. We then call bet365's homepage-pod endpoint
     `/pullpodapi/gethomepagepods?lid=32&zid=0&pd=...` via curl_cffi with
     those cookies. Cloudflare accepts the cookies for ~7 min.
  3. The cheap call returns bet365's classic delimited-text payload
     (sections separated by `\\x08`, records by `|`, fields by `;`). We
     parse it into our standard Event/Market/Outcome model.

bet365 uses **fractional odds** by default (e.g. `OD=29/20` = +145 American,
`OD=10/17` = -170). We convert to American and decimal in `_parse_odds()`.

If Playwright is unavailable or priming fails, this scraper returns an
empty list rather than crashing the API server \u2014 the aggregator falls
back to ActionNetwork's bet365 (book_id 79).

Keeps the same public interface `fetch_sport(sport)` so the aggregator does
not need to change.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .models import Event, Market, MarketType, Outcome, SportsbookSnapshot
from . import _b365_session

logger = logging.getLogger("scraper.bet365")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# bet365 NJ tenant. The lid/cid/cgid/ctid/csid params are all NJ-tenant
# defaults captured from a real browser session. They identify
# language=32 (en-US), country=198 (US), state=3 (NJ), license group=3.
B365_HOST = "https://www.nj.bet365.com"
PODS_URL = (
    f"{B365_HOST}/pullpodapi/gethomepagepods"
    "?lid=32&zid=0&pd=%23HO%23COL1%23&cid=198&cstid=1&tcstid=1"
    "&crid=54&cgid=3&ctid=198&csid=3"
)
ADDITIONAL_PODS_URL = (
    f"{B365_HOST}/pullpodapi/gethomepageadditionalpods"
    "?lid=32&zid=0&pd=%23HO%23COL1%231%23&cid=198&cstid=1&tcstid=1"
    "&crid=54&cgid=3&ctid=198&csid=3"
)

# bet365 sport class IDs (CL field). Confirmed from leftnav recon.
SPORT_CL: Dict[str, int] = {
    "nba":    18,
    "ncaab":  18,
    "wnba":   18,
    "mlb":    16,
    "nhl":    17,
    "nfl":    12,
    "ncaaf":  12,
    "soccer": 1,
    "tennis": 13,
    "golf":   7,
    "boxing": 9,
    "mma":    9,    # bet365 puts boxing+MMA under id 9 too
    "f1":     10,
}

# Reverse mapping for league naming
CL_NAME: Dict[int, str] = {
    18: "Basketball",
    16: "Baseball",
    17: "Hockey",
    12: "Football",
    1:  "Soccer",
    13: "Tennis",
    7:  "Golf",
    9:  "Combat",
    10: "Motor Sports",
}

# \u2500\u2500 Protocol parser \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# bet365's response format (their internal "MIME" / "delimited text" protocol):
#
#   <body> := <section> ( "\x08" <section> )*
#   <section> := "F|" <record> ( "|" <record> )* "|"?
#   <record> := <type> ";" <field> ( ";" <field> )*
#   <type> := "EV" | "MA" | "PA" | "MG" | "CL" | "PD" | "PS" | "XL" | ...
#   <field> := <key> "=" <value>
#
# Key record types:
#   EV  Event/container. Holds metadata for a sport/match (NA name, TT start).
#   MG  Market group. Wraps related markets (rarely carries data).
#   MA  Market. NA=name, CL=class id.
#   PA  Participant/Selection. NA=label, OD=fractional odds, HA=handicap line,
#       FI=foreign-id pointing back at parent MA.
#   CL  Class header. CL=numeric sport id.
#
# Our parser walks the records linearly maintaining a small stack:
#   current_class \u2192 current_event \u2192 current_market \u2192 [participants]
# A new EV/MA/CL closes the previous open peer and starts a new one.

_FIELD_RE = re.compile(r"([A-Z][A-Z0-9]{0,3})=([^;]*)")
_RECORD_TYPE_RE = re.compile(r"^([A-Z]{1,3});")
# Fallback: leading control char like \x04 or \x08
_CTRL_PREFIX_RE = re.compile(r"^[\x00-\x1f]+")


def _parse_record(rec: str) -> Optional[Tuple[str, Dict[str, str]]]:
    """Parse one '|'-delimited record into (type, fields_dict).
    Returns None if record is empty or malformed.
    """
    rec = _CTRL_PREFIX_RE.sub("", rec).strip()
    if not rec:
        return None
    m = _RECORD_TYPE_RE.match(rec)
    if not m:
        return None
    rtype = m.group(1)
    body = rec[m.end():]
    fields: Dict[str, str] = {}
    for fm in _FIELD_RE.finditer(body):
        fields[fm.group(1)] = fm.group(2)
    return rtype, fields


def _parse_blob(body: str) -> List[Tuple[str, Dict[str, str]]]:
    """Flatten the entire delimited body into an ordered list of (type, fields).
    Sections separated by \\x08 are concatenated since record type tells us
    what we're looking at; the section break is just a packet boundary.
    """
    out: List[Tuple[str, Dict[str, str]]] = []
    # Replace section markers with record separators so a single split works
    flat = body.replace("\x08", "|")
    for rec in flat.split("|"):
        parsed = _parse_record(rec)
        if parsed is not None:
            out.append(parsed)
    return out


def _fraction_to_american(od: str) -> Optional[int]:
    """Convert bet365 fractional odds 'A/B' to American.
       A/B with A >= B  \u2192 +(A/B*100)  rounded
       A/B with A <  B  \u2192 -(B/A*100)  rounded
       'EVS' (even money) \u2192 +100
    """
    if not od:
        return None
    s = od.strip().upper()
    if s in ("EVS", "EVEN", "1/1"):
        return 100
    if "/" not in s:
        # Sometimes bet365 ships decimal "1.91" via OD if a feature flag is on.
        try:
            d = float(s)
            return _decimal_to_american(d)
        except Exception:
            return None
    try:
        a_str, b_str = s.split("/", 1)
        a = float(a_str)
        b = float(b_str)
        if b == 0:
            return None
    except Exception:
        return None
    if a >= b:
        return int(round((a / b) * 100))
    else:
        return -int(round((b / a) * 100))


def _decimal_to_american(d: float) -> Optional[int]:
    if d <= 1.0:
        return None
    if d >= 2.0:
        return int(round((d - 1) * 100))
    return -int(round(100 / (d - 1)))


def _american_to_decimal(am: int) -> float:
    if am > 0:
        return round(1 + am / 100.0, 4)
    return round(1 + 100.0 / abs(am), 4)


def _parse_odds(od: str) -> Tuple[Optional[int], Optional[float]]:
    """Return (american, decimal) tuple."""
    am = _fraction_to_american(od)
    if am is None:
        return None, None
    return am, _american_to_decimal(am)


def _parse_point(value: Optional[str]) -> Optional[float]:
    """Parse spread/total line. bet365 uses HA= with leading sign like '+1.5'
    or '-1.5'. Returns float or None."""
    if not value:
        return None
    v = value.strip().replace("\u2212", "-")
    # Drop leading '+' so float() works
    if v.startswith("+"):
        v = v[1:]
    try:
        return float(v)
    except Exception:
        return None


def _classify_market(name: str) -> MarketType:
    n = (name or "").lower()
    if not n:
        return MarketType.OTHER
    if "money line" in n or "moneyline" in n or "match winner" in n or n == "winner":
        return MarketType.MONEYLINE
    if any(s in n for s in ("spread", "run line", "puck line", "handicap", "point spread")):
        return MarketType.SPREAD
    if "total" in n or "over/under" in n or "over under" in n or n.startswith("o/u"):
        return MarketType.TOTAL
    if any(s in n for s in (
        "player", "points", "rebounds", "assists", "strikeouts",
        "passing", "rushing", "receiving", "to score", "ace",
        "shots on goal", "saves", "hits", "home run", "homer",
    )):
        return MarketType.PLAYER_PROP
    if "team total" in n or "first half team" in n:
        return MarketType.TEAM_PROP
    if any(s in n for s in (
        "winner", "championship", "to win", "season", "futures",
        "outright", "to lift", "mvp",
    )):
        return MarketType.FUTURES
    return MarketType.OTHER


# \u2500\u2500 Builders \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
def _extract_event_teams(name: str) -> Tuple[str, str]:
    """bet365 EV.NA is typically 'Away @ Home' or 'Home v Away'. Try a few."""
    if not name:
        return "", ""
    n = name.replace("\u2014", "-")
    for sep in (" @ ", " v ", " vs ", " - "):
        if sep in n:
            a, b = n.split(sep, 1)
            a, b = a.strip(), b.strip()
            if sep == " @ ":
                # away @ home
                return b, a  # home, away
            else:
                # home v/vs/- away
                return a, b
    return name, ""


def _parse_start_time(tt: Optional[str]) -> Optional[datetime]:
    """bet365 EV.TT is YYYYMMDDHHMMSS in UTC, e.g. '20260524121000'."""
    if not tt or len(tt) < 14 or not tt.isdigit():
        return None
    try:
        return datetime(
            int(tt[0:4]), int(tt[4:6]), int(tt[6:8]),
            int(tt[8:10]), int(tt[10:12]), int(tt[12:14]),
            tzinfo=timezone.utc,
        )
    except Exception:
        return None


def _build_events_from_records(
    records: List[Tuple[str, Dict[str, str]]],
    sport: str,
    target_cl: int,
) -> List[Event]:
    """Build Event objects from a parsed pullpodapi/gethomepagepods stream.

    bet365's homepage-pods protocol uses two distinct PA shapes:

      1. **Fixture PA**: carries event metadata (no OD).
         Fields: NA=home, N2=away, FI=event_id, BC=start_time(YYYYMMDDHHMMSS),
         L3=league, FD="Home v Away".
         Lives in a section after `EV;IT=#AP#...` headers.

      2. **Price PA**: carries an outcome with OD=fractional_odds.
         Fields: ID=selection_id, FI=parent_event_id, OD=odds, HA=line.
         Lives in a section after `MA;NA=<column>;MA=<market_id>` (where
         the parent MA carries NA="Home"/"Away"/"Over"/"Under" or a
         player name and an FI tying to ONE specific event).

    Two MA shapes:
      - "Tile MA" (homepage column header): NA=column, MA=numeric,
        FI=anchor-fixture-id. Each subsequent price-PA's FI is the fixture
        being priced; we infer the column-side from MA.NA.
      - "Selection MA" (special pods like player-props): NA=full label,
        OD=fractional_odds, FI=event_id. Direct selection on MA itself.

    Both are reconciled into a `fixtures[FI] -> {markets: {name: [outcomes]}}`
    map and emitted as Event/Market/Outcome.

    EV-context shape (from Api/1/Blob per-sport blobs) also handled:
    walking EV \u2192 MA \u2192 PA(OD) hierarchy, classic structure.
    """
    # FI -> fixture metadata (only fixtures matching target_cl are recorded)
    fixtures: Dict[str, Dict[str, Any]] = {}
    # FI -> { (market_name, market_type) : [Outcome] }
    fix_markets: Dict[str, Dict[Tuple[str, MarketType], List[Outcome]]] = {}

    # Walking state
    current_cl: Optional[int] = None
    current_market_name: Optional[str] = None  # for tile-style MA -> price-PA
    current_market_side: Optional[str] = None  # MA.NA when it looks like a side label
    current_event_fi: Optional[str] = None     # for EV-context per-sport blobs
    current_event_meta: Optional[Dict[str, Any]] = None  # ditto
    in_target_sport: bool = False              # True iff current_cl == target_cl
    # FIs we've positively associated with the target sport (via an MA whose
    # CL matched target_cl, or via an EV under target CL). Used to accept
    # fixture-metadata PAs whose surrounding context didn't carry CL.
    target_fis: set = set()
    # Fixture-PAs we saw before any target-sport context was established.
    # When a later record (MA/EV/price-PA) tags an FI as target, we
    # promote that FI's pending metadata into `fixtures`. This handles
    # columnar pods where the fixture-PA arrives ahead of the tile-MA.
    pending_fixtures: Dict[str, Dict[str, Any]] = {}

    def _promote_pending(fi: str):
        meta = pending_fixtures.pop(fi, None)
        if not meta:
            return
        _record_fixture(
            fi=fi, home=meta.get("home", ""), away=meta.get("away", ""),
            start=meta.get("start"), league=meta.get("league", ""),
            live=False, desc=meta.get("desc", ""),
        )

    def _record_fixture(fi: str, home: str, away: str, start, league: str, live: bool, desc: str = ""):
        if not fi:
            return
        if fi in fixtures:
            f = fixtures[fi]
            if home and not f.get("home"): f["home"] = home
            if away and not f.get("away"): f["away"] = away
            if start and not f.get("start"): f["start"] = start
            if league and not f.get("league"): f["league"] = league
            if desc and not f.get("desc"): f["desc"] = desc
            return
        fixtures[fi] = {
            "home": home, "away": away, "start": start, "league": league,
            "live": live, "desc": desc or (f"{away} @ {home}".strip(" @")),
        }

    def _add_outcome(fi: str, market_name: str, mtype: MarketType, label: str,
                     price_american: int, price_decimal: float,
                     point: Optional[float]):
        if not fi or fi not in fixtures:
            return
        key = (market_name, mtype)
        fix_markets.setdefault(fi, {}).setdefault(key, []).append(Outcome(
            name=label or "(?)",
            price_american=price_american,
            price_decimal=price_decimal,
            point=point,
        ))

    SIDE_LABELS = {
        "home", "away", "draw", "x", "1", "2",
        "over", "under", "yes", "no", "tie",
    }

    for rtype, fields in records:
        if rtype == "CL":
            cl_val = fields.get("CL") or fields.get("ID")
            if cl_val and cl_val.lstrip("-").isdigit():
                current_cl = int(cl_val)
                in_target_sport = (current_cl == target_cl)
                # Reset market context on sport switch.
                if not in_target_sport:
                    current_market_name = None
                    current_market_side = None
                    current_event_fi = None
                    current_event_meta = None

        elif rtype == "EV":
            current_market_name = None
            current_market_side = None
            cl_field = fields.get("CL")
            if cl_field and cl_field.lstrip("-").isdigit():
                ev_cl = int(cl_field)
                # EV with explicit CL: use it to refine our sport state.
                in_target_sport = (ev_cl == target_cl)
                current_cl = ev_cl
            # else: inherit current sport state.
            if not in_target_sport:
                current_event_fi = None
                current_event_meta = None
                continue
            fi = (fields.get("ID") or fields.get("FI") or "").strip()
            if not fi:
                # IT-only EV \u2014 just a structural marker, not a real fixture.
                current_event_fi = None
                current_event_meta = None
                continue
            name = fields.get("NA") or fields.get("FD") or ""
            home, away = _extract_event_teams(name)
            league_name = fields.get("L3", "") or CL_NAME.get(target_cl, sport.upper())
            start = _parse_start_time(fields.get("TT") or fields.get("BC"))
            is_live = fields.get("PT") == "5" or fields.get("IP") == "1"
            _record_fixture(fi, home or name, away, start, league_name, is_live, name)
            current_event_fi = fi
            current_event_meta = fixtures[fi]
            target_fis.add(fi)
            _promote_pending(fi)

        elif rtype == "MA":
            cl_field = fields.get("CL")
            if cl_field and cl_field.lstrip("-").isdigit():
                ma_cl = int(cl_field)
                ma_in_target = (ma_cl == target_cl)
            else:
                ma_in_target = in_target_sport

            if not ma_in_target:
                current_market_name = None
                current_market_side = None
                continue

            ma_name = fields.get("NA") or fields.get("N2") or fields.get("MN") or ""
            ma_od = fields.get("OD")

            # Selection-style MA: full selection + odds on the same record
            # (used for some special pods like single-bet promos).
            if ma_od:
                fi = fields.get("FI") or current_event_fi or ""
                if not fi:
                    continue
                target_fis.add(fi)
                _promote_pending(fi)
                # Make sure we have a fixture row for this FI even if we
                # haven't seen the metadata PA yet \u2014 record placeholder.
                _record_fixture(
                    fi=fi, home="", away="",
                    start=None, league=CL_NAME.get(target_cl, sport.upper()),
                    live=False, desc=fields.get("N2", "") or fields.get("MN", ""),
                )
                # Update with merge-friendly N2 if it looks like "Home v Away"
                fd = fields.get("N2") or fields.get("MN") or ""
                if fd and " v " in fd:
                    h, a = _extract_event_teams(fd)
                    _record_fixture(fi, h, a, None, "", False, fd)

                am, dec = _parse_odds(ma_od)
                if am is None:
                    continue
                # MN values often look like "Money Line: NY Knicks" or
                # "Spread: NY Knicks -3.5" — strip the per-selection suffix
                # so all selections in the same market merge together.
                # Some pods omit MN entirely and put the full label in NA;
                # in that case the same parsing applies to ma_name to
                # keep market_name clean and use the suffix as outcome label.
                raw_market_name = fields.get("MN") or ""
                outcome_label = ma_name
                if raw_market_name and ":" in raw_market_name:
                    market_name = raw_market_name.split(":", 1)[0].strip()
                elif raw_market_name:
                    market_name = raw_market_name
                elif ma_name and ":" in ma_name:
                    # NA carries full "Market: Selection" — split it.
                    head, tail = ma_name.split(":", 1)
                    market_name = head.strip()
                    outcome_label = tail.strip() or ma_name
                else:
                    market_name = ma_name or "Special"
                mtype = _classify_market(market_name)
                point = _parse_point(fields.get("HA")) or _parse_point(fields.get("HD"))
                _add_outcome(fi, market_name, mtype, outcome_label, am, dec, point)
                current_market_name = None
                current_market_side = None
                continue

            # Tile-style MA: column header for the price-PAs that follow.
            current_market_side = ma_name.strip()
            if current_market_side.lower() in SIDE_LABELS:
                # Standard 2/3-way side. Use a coarse market_name from MA.MA
                # (the bet365 market-id) or fall back to a conventional name.
                market_id = fields.get("MA")
                if market_id == "1":
                    current_market_name = "Match Winner"
                elif market_id in ("3", "4", "40"):
                    current_market_name = "Match Winner"
                elif market_id in ("16", "17"):
                    current_market_name = "Total"
                elif market_id == "30":
                    current_market_name = "Spread"
                else:
                    # Generic \u2014 use the side label as part of name so we
                    # don't merge unrelated markets. Will be cleaned via
                    # _classify_market.
                    current_market_name = "Match Winner"
            else:
                # MA.NA looks like a player name or specific pick \u2014 use as
                # market name; the price PA will inherit it as the label.
                current_market_name = ma_name or "Market"
                current_market_side = ma_name

        elif rtype == "PA":
            od = fields.get("OD")
            fi = (fields.get("FI") or "").strip()

            if not od:
                # Fixture-metadata PA. Record if either:
                #   (a) we're currently inside target-sport context, OR
                #   (b) this FI was already tagged as target via a prior
                #       MA/EV in this same blob (handles columnar pods
                #       where tile-MAs come AFTER fixture-PAs but on the
                #       same FI).
                if not in_target_sport and (not fi or fi not in target_fis):
                    # Defer: stash unknown fixture-PAs so a later MA-OD
                    # or price-PA referencing this FI can promote them.
                    home = fields.get("NA", "")
                    away = fields.get("N2", "")
                    fd = fields.get("FD", "")
                    if fi and (home or away or fd):
                        league_name = fields.get("L3") or CL_NAME.get(target_cl, sport.upper())
                        start = _parse_start_time(fields.get("BC"))
                        pending_fixtures[fi] = {
                            "home": home, "away": away, "start": start,
                            "league": league_name,
                            "desc": fd or (f"{away} @ {home}".strip(" @")),
                        }
                    continue
                home = fields.get("NA", "")
                away = fields.get("N2", "")
                fd = fields.get("FD", "")
                if not (home or away or fd):
                    continue
                if fi:
                    league_name = fields.get("L3") or CL_NAME.get(target_cl, sport.upper())
                    start = _parse_start_time(fields.get("BC"))
                    _record_fixture(
                        fi=fi, home=home, away=away,
                        start=start, league=league_name,
                        live=False,
                        desc=fd or (f"{away} @ {home}".strip(" @")),
                    )
                continue

            # Price PA. Need a parent FI and a current market context.
            # Accept if either we're inside target-sport context OR the
            # FI was already tagged as target via a prior MA/EV. This
            # handles columnar pods where price-PAs trail tile-MAs.
            if not in_target_sport and (not fi or fi not in target_fis):
                # If we have a current context but the FI is unknown,
                # use the active event FI as fallback.
                if current_event_fi and current_event_fi in target_fis:
                    fi = current_event_fi
                else:
                    continue
            if current_market_name is None:
                # No active market context \u2014 we can't infer the market name.
                continue
            if not fi:
                fi = current_event_fi or ""
            if fi:
                target_fis.add(fi)
                _promote_pending(fi)
            if not fi or fi not in fixtures:
                # PA references a fixture we never recorded (probably from
                # another sport that leaked through MA filtering).
                continue
            am, dec = _parse_odds(od)
            if am is None:
                continue
            point = _parse_point(fields.get("HA")) or _parse_point(fields.get("HD"))
            label = fields.get("NA", "").strip()
            if not label:
                label = current_market_side or ""
            mname = current_market_name
            mtype = _classify_market(mname)
            _add_outcome(fi, mname, mtype, label, am, dec, point)

        # MG / PD / PS / XL \u2014 structural, ignored.

    # ── Post-processing: recover home/away for orphan fixtures ──
    # bet365 splits same matchup across multiple FIs (one per pod tile).
    # The ML pod's FI typically has no fixture-PA, only MA-OD selections
    # whose ma_name is the team name. If a fixture has no home/away but
    # has a Money-Line-classified market with exactly 2 outcomes whose
    # labels look like team names, use them.
    for fi, meta in fixtures.items():
        if meta.get("home") and meta.get("away"):
            continue
        markets_dict = fix_markets.get(fi)
        if not markets_dict:
            continue
        # Find a moneyline market with exactly 2 outcomes
        for (mname, mtype), outs in markets_dict.items():
            if mtype != "moneyline" or len(outs) != 2:
                continue
            label_a = (outs[0].name or "").strip()
            label_b = (outs[1].name or "").strip()
            # Heuristic: both labels non-empty, neither contains digits
            # like "+150" / "Over 5.5" / a colon (compound label).
            if not (label_a and label_b):
                continue
            if any(ch.isdigit() for ch in label_a + label_b):
                continue
            if ":" in label_a or ":" in label_b:
                continue
            # American odds: home is the *favorite-or-listed-second* per
            # bet365 convention, but we don't know order. Conservative:
            # treat outcome[0] as away, outcome[1] as home (matches the
            # "Away @ Home" description format used elsewhere).
            meta["away"] = meta.get("away") or label_a
            meta["home"] = meta.get("home") or label_b
            if not meta.get("desc"):
                meta["desc"] = f"{label_a} @ {label_b}"
            break

    # Materialize Events. Drop any fixture without odds.
    out: List[Event] = []
    for fi, meta in fixtures.items():
        markets_dict = fix_markets.get(fi)
        if not markets_dict:
            continue
        markets: List[Market] = []
        for (mname, mtype), outs in markets_dict.items():
            if outs:
                markets.append(Market(market_type=mtype, name=mname, outcomes=outs))
        if not markets:
            continue
        home = meta.get("home", "") or ""
        away = meta.get("away", "") or ""
        out.append(Event(
            event_id=fi,
            sport=sport,
            league=meta.get("league") or CL_NAME.get(target_cl, sport.upper()),
            home_team=home or meta.get("desc", ""),
            away_team=away,
            description=meta.get("desc") or f"{away} @ {home}".strip(" @"),
            start_time=meta.get("start"),
            is_live=meta.get("live", False),
            markets=markets,
        ))
    return out


# \u2500\u2500 HTTP fetch \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
def _fetch_b365_pods(jar: Dict[str, str], url: str) -> Optional[str]:
    """Synchronous curl_cffi call. Returns response text on 200, None otherwise.
    Routes through the same Decodo US-RCN exit Playwright primed on, so the
    Cloudflare cookie matches the IP that minted it.
    """
    try:
        from curl_cffi import requests as cf
    except Exception as e:
        logger.error("bet365: curl_cffi import failed: %s", e)
        return None

    try:
        from ._proxy import get_proxies_dict
        proxies = get_proxies_dict("US")
    except Exception:
        proxies = None

    headers = {
        "user-agent": UA,
        "accept": "*/*",
        "accept-language": "en-US",
        "referer": "https://www.nj.bet365.com/",
        "sec-ch-ua": '"Chromium";v="120", "Google Chrome";v="120", "Not.A/Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
    }

    try:
        r = cf.get(
            url,
            headers=headers,
            cookies=jar,
            proxies=proxies,
            impersonate="chrome120",
            timeout=25,
        )
    except Exception as e:
        logger.warning("bet365 fetch network error: %s", e)
        return None

    if r.status_code != 200:
        logger.warning("bet365 fetch HTTP %s for %s", r.status_code, url[:120])
        return None

    body = r.text or ""
    if len(body) < 100:
        logger.warning("bet365 fetch suspiciously small body (%d bytes)", len(body))
        return None
    return body


# \u2500\u2500 Public API \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
async def fetch_sport(sport: str) -> List[SportsbookSnapshot]:
    """
    Fetch bet365 odds for `sport` via the Cloudflare-bypass session.

    Returns [] gracefully on any failure (Playwright down, prime not yet
    succeeded, Cloudflare rotated cookies, parser found 0 events). The
    aggregator then falls back to ActionNetwork's bet365.
    """
    sport = (sport or "").lower()
    target_cl = SPORT_CL.get(sport)
    if target_cl is None:
        return []

    jar = await _b365_session.get_jar()
    if not jar:
        return []

    # Combine the two homepage endpoints \u2014 between them we get every event
    # bet365 promotes on the NJ landing page. Pull both in parallel.
    bodies = await asyncio.gather(
        asyncio.to_thread(_fetch_b365_pods, jar, PODS_URL),
        asyncio.to_thread(_fetch_b365_pods, jar, ADDITIONAL_PODS_URL),
        return_exceptions=True,
    )

    all_records: List[Tuple[str, Dict[str, str]]] = []
    for b in bodies:
        if isinstance(b, Exception) or not b:
            continue
        all_records.extend(_parse_blob(b))

    if not all_records:
        return []

    events = _build_events_from_records(all_records, sport, target_cl)
    if not events:
        return []

    league_name = events[0].league or CL_NAME.get(target_cl, sport.upper())
    return [SportsbookSnapshot(
        sportsbook="bet365",
        sport=sport,
        league=league_name,
        events=events,
        fetched_at=datetime.now(timezone.utc),
    )]
