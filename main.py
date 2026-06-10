"""
Sportsbook Odds Aggregation API v11.1.0 — Global Expansion Edition
Directly scrapes public APIs from 58+ sportsbooks across US, EU, UK, AU, Balkans, Asia, LatAm, and exchanges.
No API keys required. No third-party middlemen.

Sportsbooks (58):
  US Legal:    FanDuel, BetRivers, ESPN/DraftKings, DraftKings (direct)
  US via AN:   DraftKings, FanDuel, BetRivers, BetMGM, bet365, Caesars
  Offshore:    Bovada
  Sharp:       Pinnacle
  EU/Intl:     Kambi/Unibet, PAF, Svenska Spel, ATG, Unibet UK, Unibet SE, Unibet NL, 22Bet
  1xBet Family: 1xBet, BetWinner, Melbet, 1xBit, Linebet, MegaPari, 22Bet (Direct)
  AU:          Ladbrokes AU, Neds AU, PointsBet
  Exchanges:   Smarkets, Matchbook
  DFS:         Underdog Fantasy
  Reference:   Consensus, Opening Lines

Sports: 24 including NBA, NFL, MLB, NHL, NCAAF, NCAAB, Soccer, MMA, Boxing,
        Tennis, Golf, Cricket, Rugby, Darts, Table Tennis, Volleyball, Handball,
        Esports, Rugby League, Aussie Rules, Lacrosse, Snooker, Cycling, Motor Sports
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional, List
import uvicorn

from scrapers.aggregator import (
    fetch_sport_all_books,
    fetch_single_book,
    aggregate_events,
    find_best_odds,
    get_available_sports,
    cache,
    ALL_SPORTSBOOKS,
    SPORTSBOOK_INFO,
)
from scrapers.models import MarketType


# ─── Lifespan ─────────────────────────────────────────────────────────

async def _prefetch_background():
    """Background task to pre-fetch popular sports."""
    import asyncio
    for sport in ["nba", "nhl", "mlb"]:
        try:
            await fetch_sport_all_books(sport)
            print(f"[API] Pre-fetched {sport}")
        except Exception as e:
            print(f"[API] Error pre-fetching {sport}: {e}")
    print("[API] Background pre-fetch complete.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start server immediately, pre-fetch in background."""
    import asyncio
    print("[API] Starting up v10.0.0 — 47 sportsbooks, 24 sports")

    # Start the DraftKings Akamai-bypass cookie priming loop.
    # This launches a headless Chromium and re-primes every 5 min.
    # Failure here is non-fatal — the DK scraper falls back to returning [].
    dk_session = None
    try:
        from scrapers import _dk_session
        _dk_session.start_background()
        dk_session = _dk_session
        print("[API] DK Akamai-bypass session started.")
    except Exception as e:
        print(f"[API] DK session failed to start (DK scraping disabled): {e}")

    # Start the bet365 Cloudflare-bypass cookie priming loop. Same pattern
    # as DK; targets nj.bet365.com via Decodo US-RCN. Failure is non-fatal —
    # the bet365 direct scraper falls back to ActionNetwork in the aggregator.
    b365_session = None
    try:
        from scrapers import _b365_session
        _b365_session.start_background()
        b365_session = _b365_session
        print("[API] bet365 Cloudflare-bypass session started.")
    except Exception as e:
        print(f"[API] bet365 session failed to start (bet365 falls back to AN): {e}")

    task = asyncio.create_task(_prefetch_background())
    print("[API] Startup complete. Pre-fetching in background...")
    yield
    task.cancel()
    if dk_session is not None:
        try:
            await dk_session.shutdown()
        except Exception:
            pass
    if b365_session is not None:
        try:
            await b365_session.shutdown()
        except Exception:
            pass
    print("[API] Shutting down.")


# ─── App ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Sportsbook Odds Aggregation API — Global Expansion Edition",
    description=(
        "Real-time odds from 58+ sportsbooks via direct API scraping. "
        "Sources: Bovada, FanDuel, BetRivers, Pinnacle, Pinnacle v3, Kambi/Unibet, "
        "Unibet (Detail), PAF (Detail), ESPN/DraftKings, Smarkets, Matchbook, "
        "PAF, Svenska Spel, ATG, Unibet UK/SE/NL/BE/RO/DE/DK/CA, Ladbrokes AU, Neds AU, "
        "Underdog Fantasy, DraftKings, BetMGM, bet365, Caesars, 22Bet, PointsBet, "
        "Coolbet, ComeOn, Leon.bet, Pinnacle (Guest), "
        "MaxBet, SoccerBet RS, Merkur RS, BetOle RS, "
        "888sport IT, Bingoal, BetCity NL, "
        "1xBet, BetWinner, Melbet, 1xBit, Linebet, MegaPari, 22Bet (Direct), "
        "Consensus, Opening Lines. 24 sports. No API keys required."
    ),
    version="11.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Endpoints ────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "name": "Sportsbook Odds Aggregation API — Ultimate Edition",
        "version": "11.1.0",
        "sportsbooks": ALL_SPORTSBOOKS,
        "sportsbook_count": len(ALL_SPORTSBOOKS),
        "sport_count": len(get_available_sports()),
        "endpoints": {
            "/sports": "List available sports and sportsbook coverage",
            "/sportsbooks": "List all sportsbooks with details",
            "/odds/{sport}": "Get odds from all sportsbooks",
            "/odds/{sport}/{sportsbook}": "Get odds from a specific sportsbook",
            "/compare/{sport}": "Compare odds across sportsbooks, find best lines",
            "/events/{sport}": "Aggregated events with all sportsbook odds side-by-side",
            "/live/{sport}": "Live/in-play odds only",
            "/cache/stats": "Cache statistics",
            "/cache/clear": "Clear cache (POST)",
            "/health": "Health check",
        },
    }


@app.get("/sports")
async def list_sports():
    """List all available sports with sportsbook coverage info."""
    return {
        "total_sports": len(get_available_sports()),
        "total_sportsbooks": len(ALL_SPORTSBOOKS),
        "sports": get_available_sports(),
    }


@app.get("/sportsbooks")
async def list_sportsbooks():
    """List all sportsbooks with details."""
    return {
        "total": len(ALL_SPORTSBOOKS),
        "sportsbooks": SPORTSBOOK_INFO,
    }


@app.get("/odds/{sport}")
async def get_odds(
    sport: str,
    market: Optional[str] = Query(None, description="Filter by market type: moneyline, spread, total"),
    live_only: bool = Query(False, description="Only return live/in-play events"),
):
    """Get odds from all sportsbooks for a sport."""
    sport = sport.lower()
    available = [s["key"] for s in get_available_sports()]
    if sport not in available:
        raise HTTPException(
            status_code=404,
            detail=f"Sport '{sport}' not found. Available: {available}"
        )

    snapshots = await fetch_sport_all_books(sport)

    result = []
    for snap in snapshots:
        events = snap.events

        if live_only:
            events = [e for e in events if e.is_live]

        if market:
            market_type = None
            market_lower = market.lower()
            for mt in MarketType:
                if mt.value == market_lower:
                    market_type = mt
                    break

            if market_type:
                filtered_events = []
                for ev in events:
                    filtered_markets = [m for m in ev.markets if m.market_type == market_type]
                    if filtered_markets:
                        ev_copy = ev.model_copy()
                        ev_copy.markets = filtered_markets
                        filtered_events.append(ev_copy)
                events = filtered_events

        if events:
            result.append({
                "sportsbook": snap.sportsbook,
                "sport": snap.sport,
                "league": snap.league,
                "fetched_at": snap.fetched_at.isoformat(),
                "event_count": len(events),
                "events": [_serialize_event(e) for e in events],
            })

    return {
        "sport": sport,
        "sportsbooks_queried": len(set(s.sportsbook for s in snapshots)),
        "total_snapshots": len(result),
        "total_events": sum(r["event_count"] for r in result),
        "data": result,
    }


@app.get("/odds/{sport}/{sportsbook}")
async def get_odds_single_book(
    sport: str,
    sportsbook: str,
    market: Optional[str] = Query(None),
):
    """Get odds from a specific sportsbook."""
    sport = sport.lower()

    snapshots = await fetch_single_book(sport, sportsbook)

    result = []
    for snap in snapshots:
        events = snap.events
        if market:
            market_type = None
            for mt in MarketType:
                if mt.value == market.lower():
                    market_type = mt
                    break
            if market_type:
                filtered_events = []
                for ev in events:
                    filtered_markets = [m for m in ev.markets if m.market_type == market_type]
                    if filtered_markets:
                        ev_copy = ev.model_copy()
                        ev_copy.markets = filtered_markets
                        filtered_events.append(ev_copy)
                events = filtered_events

        if events:
            result.append({
                "sportsbook": snap.sportsbook,
                "sport": snap.sport,
                "league": snap.league,
                "fetched_at": snap.fetched_at.isoformat(),
                "event_count": len(events),
                "events": [_serialize_event(e) for e in events],
            })

    return {
        "sport": sport,
        "sportsbook": sportsbook,
        "total_events": sum(r["event_count"] for r in result),
        "data": result,
    }


@app.get("/compare/{sport}")
async def compare_odds(
    sport: str,
    market: Optional[str] = Query("moneyline", description="Market type to compare"),
    limit: int = Query(100, ge=1, le=500, description="Max events to return"),
):
    """Compare odds across sportsbooks and find best lines."""
    sport = sport.lower()
    snapshots = await fetch_sport_all_books(sport)

    if not snapshots:
        raise HTTPException(status_code=404, detail=f"No data found for sport '{sport}'")

    aggregated = aggregate_events(snapshots)
    best = find_best_odds(aggregated)

    comparisons = []
    for bo in best:
        agg = bo.event
        comp = {
            "home_team": agg.home_team,
            "away_team": agg.away_team,
            "sport": agg.sport,
            "league": agg.league,
            "start_time": agg.start_time.isoformat() if agg.start_time else None,
            "is_live": agg.is_live,
            "sportsbooks_with_odds": list(agg.sportsbook_odds.keys()),
            "num_sportsbooks": len(agg.sportsbook_odds),
            "best_prices": {},
            "all_odds": {},
        }

        target_market = market.lower() if market else "moneyline"
        if target_market in bo.best_prices:
            for outcome_name, (price, book) in bo.best_prices[target_market].items():
                comp["best_prices"][outcome_name] = {
                    "price": price,
                    "sportsbook": book,
                }

        for book_name, event in agg.sportsbook_odds.items():
            book_odds = {}
            for mkt in event.markets:
                if mkt.market_type.value == target_market:
                    for outcome in mkt.outcomes:
                        book_odds[outcome.name] = {
                            "american": outcome.price_american,
                            "decimal": outcome.price_decimal,
                            "point": outcome.point,
                        }
            if book_odds:
                comp["all_odds"][book_name] = book_odds

        if comp["best_prices"] or comp["all_odds"]:
            comparisons.append(comp)

    # Sort by number of sportsbooks (most coverage first), then apply limit
    comparisons.sort(key=lambda c: c["num_sportsbooks"], reverse=True)
    total_before_limit = len(comparisons)
    comparisons = comparisons[:limit]

    return {
        "sport": sport,
        "market": market,
        "total_events": total_before_limit,
        "returned_events": len(comparisons),
        "multi_book_events": len([c for c in comparisons if c["num_sportsbooks"] > 1]),
        "limit": limit,
        "comparisons": comparisons,
    }


@app.get("/events/{sport}")
async def get_aggregated_events(
    sport: str,
    limit: int = Query(100, ge=1, le=500, description="Max events to return"),
):
    """Get aggregated events with all sportsbook odds side-by-side."""
    sport = sport.lower()
    snapshots = await fetch_sport_all_books(sport)

    if not snapshots:
        raise HTTPException(status_code=404, detail=f"No data found for sport '{sport}'")

    aggregated = aggregate_events(snapshots)

    events = []
    for agg in aggregated:
        ev = {
            "home_team": agg.home_team,
            "away_team": agg.away_team,
            "sport": agg.sport,
            "league": agg.league,
            "start_time": agg.start_time.isoformat() if agg.start_time else None,
            "is_live": agg.is_live,
            "num_sportsbooks": len(agg.sportsbook_odds),
            "sportsbooks": {},
        }

        for book_name, event in agg.sportsbook_odds.items():
            ev["sportsbooks"][book_name] = _serialize_event(event)

        events.append(ev)

    # Sort by coverage (most sportsbooks first), then limit
    events.sort(key=lambda e: e["num_sportsbooks"], reverse=True)
    total_before_limit = len(events)
    events = events[:limit]

    return {
        "sport": sport,
        "total_events": total_before_limit,
        "returned_events": len(events),
        "limit": limit,
        "events": events,
    }


@app.get("/live/{sport}")
async def get_live_odds(sport: str):
    """Get live/in-play odds only."""
    sport = sport.lower()
    snapshots = await fetch_sport_all_books(sport)

    live_events = []
    for snap in snapshots:
        for ev in snap.events:
            if ev.is_live:
                live_events.append({
                    "sportsbook": snap.sportsbook,
                    "event": _serialize_event(ev),
                })

    return {
        "sport": sport,
        "live_count": len(live_events),
        "events": live_events,
    }


@app.get("/cache/stats")
async def cache_stats():
    return cache.stats()


@app.get("/status/dk-session")
async def dk_session_status():
    """Status of the DraftKings Akamai-bypass cookie session."""
    try:
        from scrapers import _dk_session
        return _dk_session.status()
    except Exception as e:
        return {"error": str(e), "available": False}


@app.post("/admin/dk-prime")
async def dk_prime():
    """Manually trigger a DK cookie re-prime."""
    try:
        from scrapers import _dk_session
        ok = await _dk_session.prime(force=True)
        return {"primed": ok, "status": _dk_session.status()}
    except Exception as e:
        return {"primed": False, "error": str(e)}


@app.get("/status/b365-session")
async def b365_session_status():
    """Status of the bet365 Cloudflare-bypass cookie session."""
    try:
        from scrapers import _b365_session
        return _b365_session.status()
    except Exception as e:
        return {"error": str(e), "available": False}


@app.post("/admin/b365-prime")
async def b365_prime():
    """Manually trigger a bet365 cookie re-prime."""
    try:
        from scrapers import _b365_session
        ok = await _b365_session.prime(force=True)
        return {"primed": ok, "status": _b365_session.status()}
    except Exception as e:
        return {"primed": False, "error": str(e)}


@app.post("/cache/clear")
async def clear_cache():
    cache.clear()
    return {"status": "cleared"}


@app.get("/health")
async def health():
    from scrapers._proxy import proxy_status
    return {
        "status": "healthy",
        "version": "11.0.0",
        "sportsbooks": ALL_SPORTSBOOKS,
        "sportsbook_count": len(ALL_SPORTSBOOKS),
        "sport_count": len(get_available_sports()),
        "cache": cache.stats(),
        "proxy_config": proxy_status(),
    }


@app.get("/status/books")
async def books_status():
    """
    Lists every configured bookmaker with its region, technology stack,
    and whether a proxy is configured for its region.
    Useful for diagnosing which books are reachable from current deployment.
    """
    import os
    from scrapers._proxy import proxy_status, is_us_proxy_configured
    from scrapers import kambi_factory, balkan_factory, onexbet_factory

    ps = proxy_status()
    toa_enabled = bool(os.getenv("THE_ODDS_API_KEY"))

    books = []
    # Direct scrapers
    direct_books = [
        ("Bovada", "US/Global", "proprietary", ps["US"] or True),  # Bovada is offshore, works anywhere
        ("FanDuel", "US", "proprietary", ps["US"]),
        ("DraftKings", "US", "proprietary (Akamai)", ps["US"]),
        ("BetRivers", "US", "kambi-us", ps["US"]),
        ("ESPN/DraftKings", "US", "espn-meta", True),
        ("Pinnacle", "Global", "pinnacle-api", True),
        ("Pinnacle v3", "Global", "pinnacle-api-v3", True),
        ("Pinnacle (Guest)", "Global", "pinnacle-guest", True),
        ("Kambi/Unibet", "EU/Global", "kambi", True),
        ("Smarkets", "UK", "smarkets-api", True),
        ("Matchbook", "UK", "matchbook-api", True),
        ("Ladbrokes AU", "AU", "entain-au", ps["AU"]),
        ("Neds AU", "AU", "entain-au", ps["AU"]),
        ("Underdog Fantasy", "US", "underdog-api", ps["US"]),
        ("ActionNetwork", "US", "an-meta", True),
        ("22Bet", "Global", "onexbet-family", True),
        ("PointsBet", "AU/Canada", "pointsbet-api", ps["AU"]),
        ("Unibet (Detail)", "EU", "kambi-detail", True),
        ("PAF (Detail)", "EU", "kambi-detail", True),
        ("Coolbet", "EU/LatAm", "kambi", True),
        ("ComeOn", "EU", "kambi", True),
        ("Leon.bet", "Global", "leon-api", True),
        ("MaxBet", "Balkan", "balkan-api", True),
        ("Kalshi", "US (CFTC)", "kalshi-api", True),
        ("Polymarket", "Crypto/Global", "polymarket-api", True),
    ]
    for name, region, stack, reachable in direct_books:
        books.append({
            "name": name, "region": region, "stack": stack,
            "reachable_from_current_deployment": bool(reachable),
        })

    # Kambi factory operators (all 25)
    for op_id, op in kambi_factory.KAMBI_OPERATORS.items():
        books.append({
            "name": op["name"], "region": op.get("market", "?"),
            "stack": "kambi-factory",
            "reachable_from_current_deployment": True,
        })

    # Balkan factory operators
    for op_id, op in balkan_factory.BALKAN_OPERATORS.items():
        books.append({
            "name": op["name"], "region": "Balkans",
            "stack": "balkan-factory",
            "reachable_from_current_deployment": True,
        })

    # 1xBet factory operators
    for op_id, op in onexbet_factory.ONEXBET_OPERATORS.items():
        books.append({
            "name": op["name"], "region": op.get("region", "Global"),
            "stack": "onexbet-family",
            "reachable_from_current_deployment": True,
        })

    # TheOddsAPI meta-provider (unlocks ~40 more books when enabled)
    toa_books = []
    if toa_enabled:
        toa_books = [
            "DraftKings (OddsAPI)", "FanDuel (OddsAPI)", "BetMGM (OddsAPI)",
            "Caesars (OddsAPI)", "BetRivers (OddsAPI)", "PointsBet (OddsAPI)",
            "WynnBET (OddsAPI)", "SugarHouse (OddsAPI)", "Unibet US (OddsAPI)",
            "BetOnline (OddsAPI)", "LowVig (OddsAPI)", "MyBookie (OddsAPI)",
            "Superbook (OddsAPI)",
            "bet365 (OddsAPI)", "William Hill (OddsAPI)", "Paddy Power (OddsAPI)",
            "Betfair (OddsAPI)", "Ladbrokes UK (OddsAPI)", "Coral UK (OddsAPI)",
            "BoyleSports (OddsAPI)", "BetVictor (OddsAPI)", "SkyBet (OddsAPI)",
            "Grosvenor (OddsAPI)", "Marathon Bet (OddsAPI)", "Betfred (OddsAPI)",
            "Betsson (OddsAPI)", "NordicBet (OddsAPI)", "LeoVegas (OddsAPI)",
            "888sport (OddsAPI)",
            "Sportsbet AU (OddsAPI)", "TAB AU (OddsAPI)", "PlayUp (OddsAPI)",
            "Ladbrokes AU (OddsAPI)", "Bluebet (OddsAPI)", "Boombet (OddsAPI)",
        ]
        for name in toa_books:
            books.append({
                "name": name, "region": "Via The Odds API",
                "stack": "the-odds-api",
                "reachable_from_current_deployment": True,
            })

    return {
        "total_books": len(books),
        "us_proxy_configured": is_us_proxy_configured(),
        "the_odds_api_enabled": toa_enabled,
        "proxy_regions": ps,
        "books": books,
        "how_to_unlock_us_books": {
            "option_a_us_vps": "Deploy on Railway with region=us-east4 (configured in railway.toml).",
            "option_b_us_proxy": "Set env var US_PROXY_URL=http://user:pass@us-residential-proxy:port",
            "option_c_odds_api": "Set env var THE_ODDS_API_KEY to enable aggregated feed from 40+ books",
        },
    }


# ─── Helpers ──────────────────────────────────────────────────────────

def _serialize_event(event) -> dict:
    """Serialize an Event model to dict."""
    return {
        "event_id": event.event_id,
        "sport": event.sport,
        "league": event.league,
        "home_team": event.home_team,
        "away_team": event.away_team,
        "description": event.description,
        "start_time": event.start_time.isoformat() if event.start_time else None,
        "is_live": event.is_live,
        "markets": [
            {
                "market_type": m.market_type.value,
                "name": m.name,
                "outcomes": [
                    {
                        "name": o.name,
                        "price_american": o.price_american,
                        "price_decimal": o.price_decimal,
                        "point": o.point,
                    }
                    for o in m.outcomes
                ],
            }
            for m in event.markets
        ],
    }


# ─── Run ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    workers = int(os.environ.get("WEB_CONCURRENCY", 1))
    log_level = os.environ.get("LOG_LEVEL", "info")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level=log_level,
        timeout_keep_alive=120,
    )