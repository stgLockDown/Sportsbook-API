# US Sportsbook Bot Detection Bypass — Strategy Guide

## Why Competitors Can Access US Sportsbooks and We (Currently) Can't

US-licensed sportsbooks (DraftKings, FanDuel, BetMGM, Caesars, etc.) use **three stacked defenses**:

### 1. TLS Fingerprinting (Akamai Bot Manager, Cloudflare, PerimeterX)
- They inspect the **JA3/JA4 TLS handshake fingerprint** to detect non-browser clients
- Standard Python `httpx`/`requests` produce a unique fingerprint that flags as a bot
- **Our fix:** `curl_cffi` with `impersonate="chrome"` — ✅ implemented

### 2. US Geolocation Hard Wall
- US sportsbooks legally can only serve US residents in licensed states
- They check IP geolocation → block all non-US traffic with a 403/region error page
- Our sandbox runs outside the US → blocked at the network layer
- **Fix required:** Route requests through a **US residential proxy** or run the crawler on a **US-based VPS**

### 3. JavaScript Challenge / CAPTCHA
- After TLS + geo, some books serve a JS challenge that a headless browser must solve
- Simple HTTP clients fail the challenge
- **Fix:** Use Playwright with stealth plugins, or commercial anti-bot bypass services

## Competitor Analysis: How They Do It

| Provider | Approach |
|----------|----------|
| **The Odds API** | Commercial data deal with a few books; scrapes the rest from US datacenter IPs |
| **Odds Jam** | Runs scrapers from AWS us-east-1; uses residential proxies for hardened sites |
| **Action Network** | Official B2B partnerships (DK, FanDuel) + own sportsbook license |
| **OddsShopper / BettingPros** | Proxy rotation through Bright Data/Oxylabs |

## Concrete Next Steps to Unlock US Books

### Option A (Cheapest): US VPS deployment
1. Deploy this API on **AWS Lightsail US-East ($3.50/mo)** or **Linode Dallas ($5/mo)**
2. Re-enable the `draftkings.py`, `fanduel.py`, `betrivers.py` scrapers
3. They already use the correct endpoints — will just start working with US IP

### Option B (Most Reliable): Residential Proxy Rotation
1. Subscribe to **Bright Data residential proxies** (~$500/mo entry) or **Oxylabs** or **Smartproxy**
2. Add proxy config to all US-market scrapers
3. Rotate IPs per request to avoid rate limits

### Option C (Hybrid): Commercial API fallback
1. Use **The Odds API** ($29-149/mo) as a fallback for US books
2. Keeps us at feature parity while we build our own scrapers
3. Add as a provider: `the_odds_api.py` → fetches DK/FD/BetMGM via their key

### Option D (Playwright + US Proxy):
1. Use **Playwright with stealth plugins** + US residential proxy
2. Can bypass almost any protection including JS challenges
3. Higher latency but reliable

## Recommendation

**Do both A + C**:
- Deploy the API on a US VPS ($5/mo): immediately unlocks DraftKings / FanDuel / BetRivers / ESPN scrapers that already exist in this repo
- Add The Odds API as a fallback provider: gets us ALL remaining US books for <$100/mo
- Total cost: ~$105/mo vs $500+/mo for residential proxies

## Code Changes Needed for Proxy Support

Add to `scrapers/_proxy.py`:
```python
import os
US_PROXY = os.getenv("US_PROXY_URL")  # e.g. http://user:pass@us-proxy.brightdata.com:22225

def get_client_config(region="US"):
    if region == "US" and US_PROXY:
        return {"proxies": {"https://": US_PROXY, "http://": US_PROXY}}
    return {}
```

Then in each US scraper:
```python
from ._proxy import get_client_config
async with httpx.AsyncClient(**get_client_config("US")) as client:
    ...
```