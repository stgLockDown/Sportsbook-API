# 🏈 Sportsbook Odds Aggregation API v10.0.0

Real-time sports betting odds aggregated from **47+ sportsbooks** via direct API scraping. No API keys required. No third-party middlemen.

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template/sportsbook-api)

---

## 🚀 Features

- **47+ Sportsbooks** scraped in real-time
- **24 Sports** covered (NBA, NFL, MLB, NHL, Soccer, Tennis, MMA, and more)
- **Cross-book comparison** — find the best odds instantly
- **Live odds** support for in-play betting
- **Zero API keys** — all data from publicly accessible endpoints
- **Sub-second aggregation** with smart caching (5-min TTL)
- **Railway-ready** — one-click deploy with health checks

---

## 📚 Sportsbooks Covered

| Category | Sportsbooks |
|----------|------------|
| **US Legal** | FanDuel, BetRivers, DraftKings, ESPN/DraftKings |
| **US via Action Network** | DraftKings, FanDuel, BetRivers, BetMGM, Bet365, Caesars |
| **Offshore** | Bovada |
| **Sharp** | Pinnacle, Pinnacle v3 (Arcadia), Pinnacle (Guest) |
| **EU/International** | Kambi/Unibet, Unibet (Detail), PAF (Detail), Svenska Spel, ATG, Unibet UK/SE/NL/BE/RO/DE/DK/CA, 22Bet, Coolbet, ComeOn, Leon.bet, 888sport IT, Bingoal, BetCity NL |
| **Balkans** | MaxBet, SoccerBet RS, Merkur RS, BetOle RS |
| **Australia** | Ladbrokes AU, Neds AU, PointsBet |
| **Exchanges** | Smarkets, Matchbook |
| **DFS** | Underdog Fantasy |
| **Reference** | Consensus, Opening Lines |

---

## 🏟️ Sports Covered (24)

NBA · NFL · MLB · NHL · NCAAF · NCAAB · Soccer · MMA · Boxing · Tennis · Golf · Cricket · Rugby · Darts · Table Tennis · Volleyball · Handball · Esports · Rugby League · Aussie Rules · Lacrosse · Snooker · Cycling · Motor Sports

---

## 📡 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | API info, version, available sportsbooks |
| `/health` | GET | Health check (used by Railway) |
| `/sports` | GET | List all available sports with coverage info |
| `/sportsbooks` | GET | List all sportsbooks with details |
| `/odds/{sport}` | GET | Get odds from all sportsbooks for a sport |
| `/odds/{sport}/{sportsbook}` | GET | Get odds from a specific sportsbook |
| `/compare/{sport}` | GET | Compare odds across books, find best lines |
| `/events/{sport}` | GET | Aggregated events with all book odds side-by-side |
| `/live/{sport}` | GET | Live/in-play odds only |
| `/cache/stats` | GET | Cache statistics |
| `/cache/clear` | POST | Clear the cache |

### Query Parameters

| Parameter | Endpoints | Description |
|-----------|-----------|-------------|
| `market` | `/odds`, `/compare` | Filter by market: `moneyline`, `spread`, `total` |
| `live_only` | `/odds` | Only return live/in-play events (`true`/`false`) |

### Example Requests

```bash
# Get all NBA odds
curl https://your-app.railway.app/odds/nba

# Get NBA moneyline odds only
curl https://your-app.railway.app/odds/nba?market=moneyline

# Compare NBA odds across all sportsbooks
curl https://your-app.railway.app/compare/nba

# Get odds from a specific sportsbook
curl https://your-app.railway.app/odds/nba/Bovada

# Get live NBA odds
curl https://your-app.railway.app/live/nba

# Get aggregated events with all book odds
curl https://your-app.railway.app/events/nba
```

### Example Response (`/compare/nba`)

```json
{
  "sport": "nba",
  "market": "moneyline",
  "total_events": 94,
  "multi_book_events": 94,
  "comparisons": [
    {
      "home_team": "Cleveland Cavaliers",
      "away_team": "Boston Celtics",
      "sport": "basketball",
      "league": "NBA",
      "start_time": "2026-03-09T00:00:00",
      "sportsbooks_with_odds": ["Bovada", "FanDuel", "DraftKings", "Pinnacle v3", "..."],
      "num_sportsbooks": 17,
      "best_prices": {
        "Cleveland Cavaliers": { "price": -145, "sportsbook": "Pinnacle v3" },
        "Boston Celtics": { "price": +135, "sportsbook": "Bovada" }
      },
      "all_odds": {
        "Bovada": { "Cleveland Cavaliers": { "american": -155, "decimal": 1.645 }, "..." },
        "Pinnacle v3": { "Cleveland Cavaliers": { "american": -145, "decimal": 1.69 }, "..." }
      }
    }
  ]
}
```

---

## 🚂 Deploy to Railway

### Option 1: One-Click Deploy

1. Fork this repository
2. Go to [Railway](https://railway.app)
3. Click **"New Project"** → **"Deploy from GitHub Repo"**
4. Select this repository
5. Railway auto-detects the Dockerfile and deploys
6. Your API will be live at `https://your-app.railway.app`

### Option 2: Railway CLI

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Initialize project
railway init

# Deploy
railway up
```

### Option 3: Connect GitHub Repo

1. Go to [Railway Dashboard](https://railway.app/dashboard)
2. **New Project** → **Deploy from GitHub Repo**
3. Connect your GitHub account and select `stgLockDown/Sportsbook-API`
4. Railway will auto-deploy on every push to `main`

### Environment Variables (Optional)

Railway sets `PORT` automatically. These are optional overrides:

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8000` | Server port (set by Railway) |
| `WEB_CONCURRENCY` | `1` | Number of Uvicorn workers |
| `LOG_LEVEL` | `info` | Logging level |
| `CACHE_TTL` | `300` | Cache time-to-live in seconds |

### Railway Health Check

The `/health` endpoint is configured as the health check path. Railway will monitor this endpoint and restart the service if it becomes unhealthy.

---

## 🖥️ Local Development

### Prerequisites

- Python 3.11+
- pip

### Setup

```bash
# Clone the repository
git clone https://github.com/stgLockDown/Sportsbook-API.git
cd Sportsbook-API

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Run the server
python main.py
```

The API will be available at `http://localhost:8000`

### Using Docker

```bash
# Build the image
docker build -t sportsbook-api .

# Run the container
docker run -p 8000:8000 sportsbook-api

# With environment variables
docker run -p 8000:8000 -e WEB_CONCURRENCY=2 sportsbook-api
```

---

## 🏗️ Project Structure

```
├── main.py                  # FastAPI application & endpoints
├── scrapers/
│   ├── __init__.py
│   ├── models.py            # Pydantic data models
│   ├── aggregator.py        # Core aggregation engine (800+ lines)
│   ├── actionnetwork.py     # Action Network scraper (multi-book)
│   ├── betrivers.py         # BetRivers scraper
│   ├── bovada.py            # Bovada scraper
│   ├── draftkings.py        # DraftKings scraper
│   ├── espn.py              # ESPN/DraftKings scraper
│   ├── fanduel.py           # FanDuel scraper
│   ├── kambi.py             # Kambi CDN scraper
│   ├── kambi_multi.py       # Multi-operator Kambi scraper
│   ├── ladbrokes_au.py      # Ladbrokes Australia scraper
│   ├── matchbook.py         # Matchbook exchange scraper
│   ├── neds_au.py           # Neds Australia scraper
│   ├── paf.py               # PAF (Kambi) scraper
│   ├── pinnacle.py          # Pinnacle v2 scraper
│   ├── pinnacle_v3.py       # Pinnacle v3 Arcadia scraper
│   ├── pinnacle_guest.py    # Pinnacle Guest API scraper
│   ├── pointsbet.py         # PointsBet scraper
│   ├── coolbet.py           # Coolbet (Kambi CDN) scraper
│   ├── leon.py              # Leon.bet scraper
│   ├── smarkets.py          # Smarkets exchange scraper
│   ├── twentytwobet.py      # 22Bet scraper
│   ├── underdog.py          # Underdog Fantasy scraper
│   └── unibet.py            # Unibet (Kambi detail) scraper
├── Dockerfile               # Docker build configuration
├── Procfile                 # Process file for deployment
├── railway.toml             # Railway deployment config
├── railway.json             # Railway JSON config (alternative)
├── nixpacks.toml            # Nixpacks config (Railway fallback)
├── requirements.txt         # Python dependencies
├── runtime.txt              # Python version specification
├── .env.example             # Example environment variables
├── .gitignore               # Git ignore rules
├── .dockerignore            # Docker ignore rules
└── README.md                # This file
```

---

## 📊 Data Models

### Event
```json
{
  "event_id": "unique-id",
  "sport": "basketball",
  "league": "NBA",
  "home_team": "Cleveland Cavaliers",
  "away_team": "Boston Celtics",
  "description": "Boston Celtics @ Cleveland Cavaliers",
  "start_time": "2026-03-09T00:00:00",
  "is_live": false,
  "markets": [...]
}
```

### Market
```json
{
  "market_type": "moneyline",
  "name": "Moneyline",
  "outcomes": [
    { "name": "Cleveland Cavaliers", "price_american": -155, "price_decimal": 1.645 },
    { "name": "Boston Celtics", "price_american": 130, "price_decimal": 2.30 }
  ]
}
```

### Market Types
- `moneyline` — Winner of the game
- `spread` — Point spread / handicap
- `total` — Over/under total points
- `player_prop` — Player-specific propositions
- `futures` — Future/outright markets
- `other` — Other market types

---

## ⚡ Performance

- **Cache TTL**: 5 minutes (configurable)
- **Concurrent scraping**: All sportsbooks queried simultaneously via `asyncio.gather()`
- **Graceful degradation**: If one book fails, others still return data
- **First request**: ~5-15 seconds (cold cache, all books queried)
- **Cached request**: ~50ms (instant from cache)

---

## 🤖 Bot Integration

This API is designed to be consumed by bots and automated systems. Example usage with Python:

```python
import requests

# Get best NBA odds
response = requests.get("https://your-app.railway.app/compare/nba")
data = response.json()

for game in data["comparisons"]:
    print(f"\n{game['away_team']} @ {game['home_team']}")
    print(f"  Books with odds: {game['num_sportsbooks']}")
    for team, best in game["best_prices"].items():
        print(f"  Best {team}: {best['price']} ({best['sportsbook']})")
```

---

## 📜 License

This project is for educational and personal use only. Ensure compliance with the terms of service of each sportsbook and applicable laws in your jurisdiction.

---

## 🔄 Changelog

### v10.0.0 (Current)
- **Massive expansion: +13 sportsbooks in one release**
- Added MaxBet (Serbia) — 900+ soccer, 70+ basketball, 90+ tennis with ML/spread/total
- Added SoccerBet RS — 858+ soccer, 12 sports, 2.3MB data via Balkan API
- Added Merkur RS — 900+ soccer, 12 sports, full odds via Balkan API
- Added BetOle RS — 1.3MB soccer data via Balkan API
- Added 5 new Unibet regional operators (BE, RO, DE, DK, CA) via Kambi CDN
- Added 888sport IT via Kambi CDN — 311KB+ soccer data
- Added Bingoal (Belgium) via Kambi CDN — 766KB+ soccer data
- Added BetCity NL via Kambi CDN — 2.2MB+ soccer data (809 events!)
- Created kambi_factory and balkan_factory for scalable multi-operator support
- Total: 47 sportsbooks, 24 sports, 11,500+ soccer events

### v9.0.0
- Added ComeOn (Kambi CDN) scraper — 141+ soccer events, 66+ esports events with full ML/spread/total
- Confirmed working across 17 sports via Kambi CDN integration
- Total: 36 sportsbooks, 24 sports

### v8.0.0
- Added Coolbet (Kambi CDN) scraper — 86+ soccer events with spreads & totals
- Added Leon.bet scraper — 2,700+ soccer events, 11+ NBA events with moneyline
- Added Pinnacle (Guest) scraper — 1,993+ soccer events, full ML/spread/total lines
- Total: 34 sportsbooks, 24 sports

### v7.0.0
- Added Pinnacle v3 Arcadia API (245 basketball matchups, 1,494 soccer matchups)
- Added Unibet (Kambi CDN) with full event detail (ML, spread, total)
- Added PAF (Kambi CDN) with full event detail
- Total: 31 sportsbooks, 24 sports

### v6.0.0
- Added 10 additional sportsbooks (28 total)
- Action Network multi-book integration
- 22Bet, PointsBet, Kambi multi-operator

### v5.0.0
- Initial release with 18 sportsbooks
- Core aggregation engine
- Cross-book comparison and best odds finder