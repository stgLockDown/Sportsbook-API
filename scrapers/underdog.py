"""
Underdog Fantasy DFS scraper.
Returns player prop lines with over/under odds.
7000+ lines across NBA, NFL, NHL, MLB, CBB, and more.
"""
import httpx
from datetime import datetime, timezone
from typing import List, Dict
from .models import SportsbookSnapshot, Event, Market, Outcome, MarketType

BASE_URL = "https://api.underdogfantasy.com/beta/v5/over_under_lines"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://underdogfantasy.com",
    "Origin": "https://underdogfantasy.com",
}

# Map Underdog sport IDs to our sport keys
SPORT_MAP = {
    "NBA": "nba",
    "NFL": "nfl",
    "NHL": "nhl",
    "MLB": "mlb",
    "CBB": "ncaab",
    "CFB": "ncaaf",
    "WNBA": "wnba",
    "MLS": "mls",
    "WBC": "baseball",
    "LAX": "lacrosse",
    "CS": "esports",
    "VAL": "esports",
    "ESPORTS": "esports",
    "FIFA": "esports",
    "PGA": "golf",
    "UFC": "mma",
    "SOCCER": "soccer",
    "EPL": "soccer",
    "UCL": "soccer",
}


def _parse_american(val) -> int:
    """Parse American odds string to int."""
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


def _american_to_decimal(american: int) -> float:
    if american > 0:
        return round(american / 100 + 1, 4)
    elif american < 0:
        return round(100 / abs(american) + 1, 4)
    return 0.0


async def fetch_sport(sport: str) -> List[SportsbookSnapshot]:
    """Fetch player prop lines from Underdog Fantasy."""
    async with httpx.AsyncClient(timeout=25) as client:
        try:
            r = await client.get(BASE_URL, headers=HEADERS)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"[Underdog] Error: {e}")
            return []

    lines = data.get("over_under_lines", [])
    appearances = {a["id"]: a for a in data.get("appearances", [])}
    games = {g["id"]: g for g in data.get("games", [])}
    players = {p["id"]: p for p in data.get("players", [])}

    # Group lines by game
    game_lines: Dict[int, list] = {}
    for line in lines:
        over_under = line.get("over_under", {})
        appearance_id = over_under.get("appearance_stat", {}).get("appearance_id") if over_under else None
        
        if not appearance_id:
            # Try from options
            for opt in line.get("options", []):
                aid = opt.get("appearance_id")
                if aid:
                    appearance_id = aid
                    break
        
        if not appearance_id:
            continue
            
        app = appearances.get(appearance_id, {})
        match_id = app.get("match_id")
        
        if not match_id:
            continue
        
        game = games.get(match_id, {})
        game_sport = game.get("sport_id", "")
        
        # Filter by sport
        mapped_sport = SPORT_MAP.get(game_sport, game_sport.lower())
        if mapped_sport != sport:
            continue
        
        if match_id not in game_lines:
            game_lines[match_id] = []
        game_lines[match_id].append((line, app, game))

    events = []
    for match_id, line_group in game_lines.items():
        if not line_group:
            continue
        
        _, _, game = line_group[0]
        game_title = game.get("full_team_names_title", game.get("abbreviated_title", ""))
        
        # Parse teams
        if " @ " in game_title:
            parts = game_title.split(" @ ")
            away_team = parts[0].strip()
            home_team = parts[1].strip()
        elif " vs " in game_title:
            parts = game_title.split(" vs ")
            home_team = parts[0].strip()
            away_team = parts[1].strip()
        else:
            home_team = game_title
            away_team = ""
        
        # Build markets from lines
        markets = []
        for line, app, _ in line_group:
            player_id = app.get("player_id", "")
            player = players.get(player_id, {})
            player_name = f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
            if not player_name:
                player_name = "Unknown"
            
            over_under = line.get("over_under", {})
            stat_type = ""
            stat_value = None
            
            if over_under:
                appearance_stat = over_under.get("appearance_stat", {})
                stat_type = appearance_stat.get("display_stat", "")
                stat_value = line.get("stat_value") or over_under.get("stat_value")
            
            if not stat_type:
                stat_type = "Prop"
            
            try:
                stat_value = float(stat_value) if stat_value else None
            except:
                stat_value = None
            
            market_name = f"{player_name} - {stat_type}"
            
            outcomes = []
            for opt in line.get("options", []):
                choice = opt.get("choice", "")
                american_str = opt.get("american_price", "")
                american = _parse_american(american_str)
                
                if american == 0:
                    continue
                
                decimal_odds = _american_to_decimal(american)
                
                outcomes.append(Outcome(
                    name=f"{choice.title()} {stat_value}" if stat_value else choice.title(),
                    price_american=american,
                    price_decimal=decimal_odds,
                    point=stat_value,
                    description=f"{player_name} {stat_type}",
                ))
            
            if outcomes:
                markets.append(Market(
                    market_type=MarketType.PLAYER_PROP,
                    name=market_name,
                    outcomes=outcomes,
                ))
        
        if markets:
            events.append(Event(
                event_id=str(match_id),
                sport=sport,
                league=game.get("sport_id", sport.upper()),
                home_team=home_team,
                away_team=away_team,
                description=game_title,
                start_time=None,
                is_live=False,
                markets=markets,
            ))

    snapshots = []
    if events:
        snapshots.append(SportsbookSnapshot(
            sportsbook="Underdog Fantasy",
            sport=sport,
            league=sport.upper(),
            events=events,
            fetched_at=datetime.now(timezone.utc),
        ))

    return snapshots