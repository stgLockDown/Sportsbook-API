# Sportsbook API - Final Research Report

## Executive Summary

After comprehensive research across **8 rounds** testing **170+ endpoints** from **100+ sportsbooks**, we have determined that the current v8.0.0 API with **34 working sportsbooks** represents the practical maximum of publicly accessible odds APIs without advanced infrastructure or paid services.

---

## Research Phases Overview

### Phase 1-3: Initial Discovery (Rounds 1-4)
**Result**: Built the core API with 31 working sportsbooks
- Identified and integrated Kambi operators (Coolbet, PAF, etc.)
- Found working APIs from various regions (US, EU, Australia, Asia)
- Established the foundation for the aggregation system

### Phase 4: Recent Additions (Round v8.0.0)
**Result**: Added 3 new sportsbooks
- **Coolbet** (Kambi CDN): 86+ soccer events
- **Leon.bet**: 2,700+ soccer events, NBA/NHL/MMA/Tennis
- **Pinnacle (Guest)**: 1,993+ soccer events with full ML/spread/total
- Total: **34 working sportsbooks**

### Phase 5: Comprehensive Expansion Testing (Rounds 5-8)

#### Round 5: Major Books (24 tested)
- Bet365, 188Bet, Barstool, BetVictor, Bodog, etc.
- **Result**: All blocked by Cloudflare, DNS issues, or authentication

#### Round 6: Kambi Operators (37 tested)
- US Unibet, EU Unibet variants, global operators
- **Result**: All returned 429 Too Many Requests (rate limiting)

#### Round 7: Crypto/Esports Books (18 tested)
- Stake.com, Nitrogen, etc.
- **Result**: All blocked (403/404/301/302)

#### Round 8: Comprehensive ABC Testing (170 endpoints)

**Category 8A: Esports Books (35 endpoints)**
- Thunderpick, Rivalry, GG.BET, Unikrn, Loot.bet, BetOnline, MyBookie
- **Result**: 0 successful - DNS errors, Cloudflare, timeouts

**Category 8B: European Books (50 endpoints)**
- 10Bet UK/EU, NetBet UK/France, ComeOn, SpeedyBet, Interwetten, etc.
- **Result**: 0 successful - 403 Forbidden, 404 Not Found, HTML responses

**Category 8C: Crypto Books (35 endpoints)**
- Nitrogen, Sportsbet.io, BC.Game, 1xBit, Cloudbet, Bitcasino
- **Result**: 0 successful - Cloudflare, DNS errors, HTML responses

**Category 8D: Mobile/WebSocket (50 endpoints)**
- Bet365 Mobile, DraftKings, FanDuel, PointsBet, BetMGM, etc.
- **Result**: 0 successful - 403 Forbidden, DNS errors, authentication required

---

## Total Research Statistics

| Metric | Count |
|--------|-------|
| **Total Sportsbooks Tested** | 100+ |
| **Total Endpoints Tested** | 170+ |
| **Working Sources Found** | 34 |
| **Blocked Sources** | 70+ |
| **Success Rate** | 33% (34/100+) |

---

## Failure Analysis

### Main Obstacles (in order of frequency)

1. **Cloudflare Protection (403 Forbidden)** - 40%
   - Used by: Bet365, GG.BET, BetOnline, NetBet, ComeOn, Interwetten, BetStars, Sportsbet.io, Bitcasino, Bet365 Mobile
   - Sophisticated anti-bot measures block automated requests

2. **DNS Errors (Subdomain doesn't exist)** - 18%
   - Used by: Thunderpick, Rivalry, Unikrn, VBit Casino, BetMGM Mobile, Caesars Mobile, Bwin Mobile
   - API subdomains often don't exist publicly

3. **404 Not Found (Endpoints don't exist)** - 15%
   - Used by: MyBookie Esports, 10Bet UK, NetBet France, SpeedyBet, DraftKings, PointsBet, Cloudbet
   - Public JSON endpoints simply don't exist

4. **HTML Responses (Error pages)** - 13%
   - Used by: 10Bet EU, Merkur Sports, Nitrogen, BC.Game, William Hill Mobile
   - Sites return HTML error pages instead of JSON

5. **Timeouts (Geo-blocking)** - 9%
   - Used by: Loot.bet, Betway Mobile
   - Sites block requests from certain regions

6. **Authentication Required (401)** - 3%
   - Used by: FanDuel, Cloudbet
   - Requires user account/session

7. **Other (Rate limiting, redirects)** - 2%
   - Used by: 1xBit (203), Kambi operators (429)

---

## Current API Capabilities

### v8.0.0 Summary
- **34 Working Sportsbooks**
- **24 Sports Supported**
- **Comprehensive Coverage**: Soccer, Basketball, Hockey, Tennis, MMA, Baseball, Football, etc.

### Top Performers by Event Count
1. **Leon.bet**: 2,700+ soccer events
2. **Pinnacle (Guest)**: 1,993+ soccer events with full betting markets
3. **Coolbet**: 86+ soccer events
4. **MyBookie**: 500+ events across all sports
5. **BetNow**: 400+ events across all sports

---

## Recommendations

### Option 1: Accept Current State ✅ RECOMMENDED
The current 34-sportsbook API is comprehensive and represents the practical maximum of publicly accessible APIs without significant infrastructure investment.

**Pros:**
- Stable and reliable
- Covers major markets
- No additional costs
- Easy to maintain

**Cons:**
- Missing some premium books (Bet365, DraftKings, FanDuel)
- Limited to public APIs

### Option 2: Paid Aggregation Services
Subscribe to professional odds aggregation services that have partnerships with sportsbooks.

**Services:**
- **The Odds API**: Free tier + paid plans
- **OddsJam API**: Professional service
- **Oddsmarket**: Free tier available
- **Sportmonks**: Football-focused
- **Goalserve**: Enterprise solution

**Pros:**
- Access to premium books
- Reliable data
- No maintenance needed

**Cons:**
- Monthly costs ($50-$500+/month)
- API rate limits
- Terms of service restrictions

### Option 3: Advanced Infrastructure
Invest in infrastructure to bypass protections.

**Requirements:**
- **Residential Proxies**: $50-$200/month
- **Browser Automation**: Puppeteer/Playwright
- **Cloudflare Bypass**: Advanced techniques
- **IP Rotation**: Proxy pools

**Pros:**
- Access to any sportsbook
- Full control
- Can be customized

**Cons:**
- High complexity
- Ongoing costs
- Legal/ethical concerns
- Risk of being banned

### Option 4: Focus on Emerging Markets
Monitor and integrate new sportsbooks as they launch.

**Strategy:**
- Monitor new crypto book launches
- Track regional regulatory changes
- Test new APIs as they appear
- Focus on less competitive markets

**Pros:**
- Lower security initially
- First-mover advantage
- Potential growth

**Cons:**
- Uncertain reliability
- Limited event coverage
- Requires ongoing monitoring

---

## Conclusion

### Research Verdict
After extensive testing of 100+ sportsbooks and 170+ endpoints, we have determined that:

1. **The current 34-sportsbook API is comprehensive** and represents the majority of publicly accessible odds APIs
2. **Major sportsbooks (Bet365, DraftKings, FanDuel, etc.) are heavily protected** by Cloudflare and require advanced infrastructure or partnerships to access
3. **Most smaller books either don't have public APIs** or are similarly protected
4. **The sports betting industry has matured** in security measures, making unauthorized access extremely difficult

### Recommended Action
**Accept the current v8.0.0 API as the production-ready solution** with 34 working sportsbooks. This provides:
- Comprehensive coverage of major markets
- Reliable data from multiple sources
- Cost-effective operation
- Easy maintenance and scalability

### Future Considerations
If more sources are needed in the future, consider:
1. **Paid aggregation services** for premium books
2. **Partnership agreements** with sportsbooks
3. **Monitoring emerging markets** for new opportunities
4. **Gradual infrastructure investment** if business requirements demand it

---

## Files Available for Review

All research findings are documented in the repository:
- `research_summary.md` - Overview of all research phases
- `research_round8_summary.md` - Detailed breakdown of Round 8
- `research_8a_results.txt` - Esports books test results
- `research_8b_results.txt` - European books test results
- `research_8c_results.txt` - Crypto books test results
- `research_8d_results.txt` - Mobile/WebSocket test results
- `research_results_r5.json` - Round 5 detailed results
- `research_results_r7.json` - Round 7 detailed results
- `kambi_operators_r6.json` - Kambi operators test results

---

**Report Generated**: 2026-03-16
**API Version**: v8.0.0
**Total Sportsbooks**: 34
**Status**: Production Ready