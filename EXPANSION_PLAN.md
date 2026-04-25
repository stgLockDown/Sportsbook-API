# Sportsbook Expansion Plan — Path to 100+ Books

## Current Status (after v13 push)

### Built-in Scrapers: 62 books directly reachable
- 25+ direct scrapers (Bovada, Pinnacle guest, ESPN, Smarkets, etc.)
- 23 Kambi factory operators (Unibet, 888sport, Rush Street, Holland Casino, etc.)
- 7 Balkan factory operators
- 7 OneXBet family operators
- 2 prediction markets (Kalshi, Polymarket)
- **Now with US proxy support** — US books unlock once deployed in US region

### Via The Odds API (meta-provider, 35+ more books)
When `THE_ODDS_API_KEY` env var is set, we gain access to:
- **US (13+):** DraftKings, FanDuel, BetMGM, Caesars, BetRivers, PointsBet, WynnBET, SugarHouse, Unibet US, BetOnline, LowVig, MyBookie, Superbook
- **UK (12+):** bet365, William Hill, Paddy Power, Betfair, Ladbrokes UK, Coral UK, BoyleSports, BetVictor, SkyBet, Grosvenor, Marathon Bet, Betfred
- **EU (4+):** Betsson, NordicBet, LeoVegas, 888sport
- **AU (6+):** Sportsbet AU, TAB AU, PlayUp, Ladbrokes AU, Bluebet, Boombet

### **Total potential: 62 direct + 35 OddsAPI = 97 books** ✅

## Deployment Configuration (v13)

### Railway
- `railway.toml` sets `region = "us-east4"` (Virginia, US)
- This alone unlocks DK/FD/BetRivers/ESPN/ActionNetwork/PointsBet/Underdog/Kalshi

### Environment Variables
| Variable | Purpose |
|----------|---------|
| `THE_ODDS_API_KEY` | Enables TheOddsAPI meta-provider (40+ books) |
| `US_PROXY_URL` | Route US scrapers through a US residential proxy |
| `UK_PROXY_URL` | Route UK scrapers through a UK proxy |
| `EU_PROXY_URL` | Route EU scrapers through an EU proxy |
| `AU_PROXY_URL` | Route AU scrapers through an AU proxy |

## How to Reach 100+ Books Post-Deploy

### Phase 1 (Immediate — no cost)
Deploy to `us-east4` via Railway:
- Unlocks: DraftKings, FanDuel, BetRivers, ESPN/DK, Bovada, ActionNetwork, PointsBet, Underdog, Kalshi
- **Net gain: all US books reachable** — brings us from 55 → 62 active

### Phase 2 ($29/mo)
Set `THE_ODDS_API_KEY`:
- Adds ~35 more books via aggregated feed
- **Net gain: 62 → 97 books**

### Phase 3 (Advanced)
Add residential proxies:
- `AU_PROXY_URL`: Unlocks Sportsbet AU direct, TAB AU, BlueBet, BoomBet
- `EU_PROXY_URL`: Unlocks Betano, Winamax, Tipico, Betsson group
- **Net gain: 97 → 110+ books**

## Unprobed but Promising Targets

### Crypto/Offshore (location-blocked from this sandbox)
- Stake.com (sports fixtures API exists, need residential proxy)
- BetOnline.ag (api-offering.betonline.ag — Cloudflare geo-blocked)
- MyBookie.ag, SportsBetting.ag, BetUS, BetAnySports (ring of sister-sites)
- Bookmaker.eu

### Altenar-powered
Betsafe, Betsson, NordicBet, LeoVegas moved away from Altenar to proprietary platforms.

### SBTech / Entain cds-api
Bwin, BetMGM, Ladbrokes UK, Coral UK, Sportingbet, PartyCasino, BetVictor — 
all use the same `cds-api/bettingoffer/fixtures` endpoint with an `x-bwin-accessid` 
header that differs per region. Access IDs are JS-injected and short-lived.
**TheOddsAPI covers all of these.**

### Asian
SBOBET, 188bet, 12bet, M88, Fun88 — all use closed agent-only APIs.
**TheOddsAPI does not cover these — would need dedicated scrapers per book.**