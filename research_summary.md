# Sportsbook API Research Summary

## Current Status (v8.0.0)
- **Total Sportsbooks**: 34
- **Sports**: 24
- **Working Sources**: 34

## Recent Additions (v8.0.0)
1. **Coolbet** (Kambi CDN) - 86+ soccer events
2. **Leon.bet** - 2,700+ soccer events, NBA/NHL/MMA/Tennis
3. **Pinnacle (Guest)** - 1,993+ soccer events with full ML/spread/total

---

## Research Findings - Round 5 & 6

### Blocked/Rate Limited Sources
Most major sportsbooks are heavily protected:

| Sportsbook | Status | Reason |
|------------|--------|--------|
| Bet365 | 403 | Cloudflare/Anti-bot |
| 188Bet | DNS Error | No service |
| Barstool | DNS Error | Site down/moved |
| BetVictor | DNS Error | No service |
| Betway EU | 302 | Redirect to auth |
| Marathonbet | 403 | Cloudflare |
| Bodog | 301 | Redirect to auth |
| Unibet Main | DNS Error | No service |
| BetMGM | 301 | Redirect to auth |
| Paddy Power | 403 | Anti-bot |
| Sports Interaction | 403 | Anti-bot |
| 1xBet | 302 | Redirect to auth |
| WynnBET | 404 | Not found |
| Coral | 301 | Redirect to auth |
| Melbet | 302 | Redirect to auth |
| SBObet | 302 | Redirect to auth |
| William Hill UK | 404 | Not found |
| WilliamHill EU | 301 | Redirect to auth |
| Dafabet | 302 | Redirect to auth |

### Kambi Operator Research (Round 6)
Tested 37 additional Kambi operators - all returned **429 Too Many Requests**:

- **US Unibet**: new_jersey, pennsylvania
- **EU Unibet**: belgium, italy, germany, uk, ireland, sweden, denmark, estonia, latvia, poland, greece, romania
- **Global**: australia, canada
- **Other Kambi books**: napoleon_games, 32red, grosvenor, 888_sport, stanleybet_romania, betwarrior, parx_casino, mybet, redbet, betplay, leovegas, betuk, casumo, kindred, storspelare, jokerbet, happybet, betsson, nordicbet, betsafe, rio_all_suite_hotel_casino

**Conclusion**: Kambi operators heavily rate limit API access. Only a few are accessible (Coolbet, PAF, Unibet variants we already have).

---

## Potential New Sources to Explore

### 1. Alternative Odds Aggregators
These services aggregate odds from multiple books and may have public APIs:

- **OddsJam** - Requires API key (paid service)
- **The Odds API** - Free tier available, requires API key
- **Oddsmarket** - Free tier available, requires API key
- **Sportmonks** - Football-focused, requires API key
- **Goalserve** - Enterprise solution, paid

### 2. Exchange APIs
Betting exchanges often have more open APIs:

- **Betfair API** - Requires account + key
- **Smarkets API** - Requires account (we have Smarkets working)
- **Matchbook API** - Requires account (we have Matchbook working)
- **Betdaq API** - Requires account + key

### 3. Regional Books (May Have Looser Security)

**Canadian:**
- Sports Interaction (403 blocked)
- Bodog (301 redirect to auth)

**Australian:**
- Sportsbet.com.au (403 blocked in previous tests)
- TAB AU (HTML, no JSON API)

**Asian:**
- SBObet (302 redirect)
- 188Bet (DNS error)
- Dafabet (302 redirect)

### 4. Smaller/Regional European Books

**Nordic Countries:**
- Kindred Group brands (already covered via Unibet variants)
- ComeOn (not tested)
- SpeedyBet (not tested)

**UK:**
- Ladbrokes UK (we have Ladbrokes AU working)
- Coral UK (301 redirect)
- BetVictor UK (DNS error)
- 10Bet (not tested)
- NetBet (not tested)

**Spain/Italy/Germany:**
- Bwin (403 blocked previously)
- Sportium (not tested)
- Interwetten (not tested)
- Merkur Sports (not tested)

### 5. Esports-Focused Books
May have less strict security:

- Thunderpick (not tested)
- Loot.bet (not tested)
- Rivalry (not tested)
- GG.BET (not tested)
- Unikrn (not tested)

### 6. Crypto Sportsbooks
Often have looser security:

- Cloudbet (401 requires API key)
- Nitrogen Sports (not tested)
- Sportsbet.io (not tested)
- Stake.com (404 blocked previously)
- BC.Game (not tested)
- 1xBit (not tested)

---

## Recommendations for Next Steps

### Priority 1: Test Esports & Crypto Books (Low Security)
These markets are newer and may have more accessible APIs:

```python
# Books to test:
- Thunderpick
- Loot.bet
- Rivalry
- Nitrogen Sports
- Sportsbet.io
- BC.Game
- 1xBit
```

### Priority 2: Test Regional European Books
Smaller books may have less sophisticated protection:

```python
# Books to test:
- 10Bet (UK)
- NetBet (UK/France)
- ComeOn (Scandinavia)
- SpeedyBet (Scandinavia)
- Interwetten (Europe)
- Merkur Sports (Germany)
```

### Priority 3: Explore Alternative Data Sources
Not direct sportsbook APIs, but aggregators:

```python
# Potential sources:
- OddsJam free tier (if available)
- The Odds API free tier
- Oddsmarket free tier
- Betting exchanges (Betfair/Smarkets with accounts)
```

### Priority 4: Mobile App APIs
Many sportsbooks have mobile APIs that might be more accessible:

```python
# Mobile endpoints to explore:
- Bet365 mobile API
- Bet365 in-play data API
- Other books' mobile endpoints
```

---

## Technical Approaches to Consider

### 1. Mobile App Reverse Engineering
- Intercept mobile app API calls
- Many books use different endpoints for mobile
- May have less strict authentication

### 2. WebSocket Connections
- Some books use WebSocket for live odds
- Real-time data streams
- May be more accessible than REST APIs

### 3. GraphQL Endpoints
- Modern books like DraftKings use GraphQL
- Single endpoint with flexible queries
- Need to discover the schema

### 4. Websocket/Browser Automation
- Use browser automation for protected sites
- Slower but more reliable for blocked APIs
- Can bypass some anti-bot measures

---

## Summary

**Working Sources**: 34 sportsbooks
**Blocked Sources**: 60+ tested and blocked

**Main Obstacles**:
1. Cloudflare protection (Bet365, Marathonbet, others)
2. Authentication requirements (301 redirects)
3. Rate limiting (Kambi operators)
4. DNS issues (site closures)
5. 403 Forbidden (anti-bot measures)

**Best Opportunities**:
1. Esports-focused books (Thunderpick, Rivalry, etc.)
2. Crypto sportsbooks (Nitrogen, Sportsbet.io, etc.)
3. Smaller European books (10Bet, ComeOn, etc.)
4. Mobile app API endpoints
5. WebSocket-based odds feeds

**Recommendation**: Focus on testing Esports and Crypto books first, as these markets are newer and likely have less sophisticated security measures. Also consider exploring mobile app endpoints and WebSocket connections as alternative data sources.