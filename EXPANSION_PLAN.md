# Sportsbook Expansion Plan — Path to 100+ Books

## Current Count (after this push)
- Core scrapers: ~15 (Bovada, FanDuel, BetRivers, Pinnacle, ESPN, Smarkets, Matchbook, Ladbrokes AU, Neds AU, Underdog, DraftKings, ActionNetwork, 22Bet, PointsBet, ComeOn, MaxBet, Leon, Coolbet, Unibet detail, PAF detail, Pinnacle v3/Guest)
- Kambi factory: 25+ operators (Unibet UK/NL/AU/FI/SE/BE/RO/DE/DK/CA, 888sport UK/IT, BetRivers NY, Rush Street, Holland Casino, ATG, Svenska Spel, Mr Green, Paf, LaFDJ, Napoleon, Bingoal, BetCity NL)
- Balkan factory: 4 operators (SoccerBet RS, MaxBet BA, MaxBet MK, BetOle RS)
- OneXBet factory: 6 operators (1xBet, 1xBit, BetWinner, Melbet, Linebet, MegaPari, 22Bet-direct)
- Prediction markets: 2 (Kalshi, Polymarket)

**Approximate total: ~55-60 distinct books accessible via API**

## Gap to 100+: Need ~45 more books

## Phase 1 — High-Value JSON APIs (confirmed working)
- [ ] BetOpenly (US exchange) — curl_cffi OK
- [ ] Dafabet (Asian) — 77KB JSON confirmed
- [ ] Grosvenor (UK) — 10KB JSON confirmed
- [ ] Fonbet (RU) — 2KB JSON confirmed
- [ ] Bet9ja (Nigeria) — 3KB JSON confirmed

## Phase 2 — Sportradar/Betradar Feed consumers
Many books use the same Sportradar odds feed. Identify operators:
- [ ] FortunaCZ — Sportradar feed
- [ ] Tipsport — Sportradar feed
- [ ] Chance.cz — Sportradar feed

## Phase 3 — SBTech (now Entain tech stack) consumers
- [ ] BetMGM (attempt direct)
- [ ] Party Poker sports
- [ ] Borgata

## Phase 4 — Crypto / Offshore (less geo-blocked)
- [ ] Stake.com (if public API)
- [ ] BetUS
- [ ] MyBookie
- [ ] BetOnline
- [ ] SportsBetting.ag
- [ ] Bookmaker.eu
- [ ] BetAnySports
- [ ] Heritage Sports

## Phase 5 — Exchange / P2P
- [ ] Betfair Exchange (via API)
- [ ] BetDAQ
- [ ] ProphetX (US exchange)
- [ ] Sporttrade (US exchange)

## Phase 6 — Additional Kambi operators to trial
- [ ] DK/JP/PT/FR Unibet variants
- [ ] JackMobile
- [ ] Napoleon (already tried)
- [ ] Casinolab
- [ ] Casino777

## Phase 7 — AU/NZ Market (Entain / Tabcorp)
- [ ] TAB NZ
- [ ] TAB AU
- [ ] Sportsbet AU
- [ ] BlueBet AU
- [ ] Palmerbet AU
- [ ] BoomBet AU
- [ ] PlayUp AU

## Phase 8 — EU Operators
- [ ] Betsson
- [ ] Betano
- [ ] Superbet
- [ ] SISAL IT
- [ ] Snai IT
- [ ] Eurobet IT
- [ ] William Hill IT
- [ ] Goldbet IT
- [ ] Tipico DE
- [ ] Oddset DE
- [ ] BetClic FR
- [ ] ParionsSport FR (LaFDJ)
- [ ] PMU FR
- [ ] Zeturf FR

## Phase 9 — Asian Operators
- [ ] SBOBET
- [ ] 1XBet (already have)
- [ ] Bet365 Asia
- [ ] Marathonbet
- [ ] 188bet
- [ ] 12bet
- [ ] M88
- [ ] Fun88

## Bot Detection Bypass Strategy for US Books
1. curl_cffi with Chrome TLS impersonation — partial (blocked by geo)
2. US residential proxy rotation (Bright Data, Oxylabs, ScraperAPI)
3. Run deployment on a US-based VPS (DO SFO, AWS us-east, Linode Dallas)
4. Scraper fallback: The Odds API aggregated feed (fallback data source)