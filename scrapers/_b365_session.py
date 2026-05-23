"""
bet365 Cloudflare-bypass session manager.

bet365's public sportsbook is fronted by Cloudflare Bot Management, which
blocks all direct httpx/curl_cffi calls (returns 403 with `__cf_bm` set, no
useful body) when hit from a sandbox/datacenter IP.

A real headless Chromium browser running through a residential ISP exit
(Decodo US-RCN) passes Cloudflare's checks cleanly and receives a workable
cookie set:

  - __cf_bm   : Cloudflare bot-management cookie
  - pstk      : bet365 session token
  - swt       : bet365 security web token
  - aps03     : state/locale config (e.g. "ct=198&cg=3&cst=3&...")
  - rmbs      : ?

With those cookies in hand we can replay arbitrary calls to
`www.nj.bet365.com/Api/1/Blob?...` and `pullpodapi/gethomepagepods` via
ordinary HTTP for ~5+ minutes before the cookies expire.

This module:
  * Owns a single global Playwright browser instance.
  * Primes the cookie jar on startup and re-primes every PRIME_INTERVAL_SEC.
  * Exposes `get_jar()` for scrapers to read the current cookie dict.
  * Is fully optional \u2014 if Playwright import or chromium launch fails, the
    module sets `READY=False` and scrapers fall back to ActionNetwork.

Recon vs DraftKings & Caesars (see docs/adr/0001 for Caesars):
  - DK: Akamai sensor cookie, cookie-replay works, similar pattern.
  - bet365: Cloudflare __cf_bm only, no challenge-ride needed, simpler.
  - Caesars: AWS WAF Bot Control \u2014 token signature-bound to per-request
    telemetry, replay rejected. Stays on ActionNetwork.

NJ subdomain (`nj.bet365.com`) is targeted because (a) bet365 is licensed
in NJ so all major sport markets are served, and (b) our Decodo US-RCN
exit (Boston, MA) gets routed to the NJ tenant cleanly. The generic
`www.bet365.com` redirects to a "where do you want to play" splash from MA.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("b365_session")

# Reuse the puppeteer-extra-stealth-equivalent evasion suite we built for DK
# (17 evasions, 9KB). Cloudflare BM uses the same browser fingerprinting
# vectors as Akamai; one stealth script handles both. Loaded once at module
# import to avoid re-reading on every prime.
try:
    _STEALTH_JS = (Path(__file__).parent / "_dk_stealth.js").read_text()
    logger.info("b365-session: loaded shared stealth JS (%d bytes)", len(_STEALTH_JS))
except Exception as e:  # pragma: no cover
    logger.warning("b365-session: failed to load _dk_stealth.js (%s); using minimal fallback", e)
    _STEALTH_JS = (
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"
        "Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});"
        "window.chrome={runtime:{}};"
    )

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Page used to prime cookies. NJ tenant is bet365's standard US deployment.
# Override via env if a different state subdomain is needed (CO/IA/KY/OH/VA).
PRIME_URL = os.getenv("B365_PRIME_URL", "https://nj.bet365.com/")

# Re-prime every 5 min. Cloudflare __cf_bm typically lasts ~30 min, plus the
# bet365 pstk/swt are session-bound and shouldn't expire mid-run, so 5 min
# leaves a healthy margin.
PRIME_INTERVAL_SEC = int(os.getenv("B365_PRIME_INTERVAL_SEC", "300"))

# How long after a prime we still consider cookies fresh enough. If a request
# would land outside this window we trigger a re-prime first.
COOKIE_TTL_SEC = int(os.getenv("B365_COOKIE_TTL_SEC", "420"))  # 7 min

# bet365 wants a US residential IP \u2014 share the DK proxy env var since both
# scrapers run through the same Decodo US-RCN exit.
US_PROXY_URL = os.getenv("US_PROXY_URL", "").strip()


class B365Session:
    """Singleton-ish session manager."""

    def __init__(self) -> None:
        self.jar: Dict[str, str] = {}
        self.last_prime_ts: float = 0.0
        self.ready: bool = False
        self.priming: bool = False
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self._browser = None
        self._pw = None
        self._available = self._check_availability()

    @staticmethod
    def _check_availability() -> bool:
        try:
            import playwright  # noqa: F401
            return True
        except Exception as e:
            logger.warning("Playwright unavailable, bet365 direct scraper will return []: %s", e)
            return False

    @staticmethod
    def _proxy_arg() -> Optional[dict]:
        if not US_PROXY_URL:
            return None
        m = re.match(r"https?://([^:]+):([^@]+)@(.+)", US_PROXY_URL)
        if not m:
            return None
        return {
            "server": f"http://{m.group(3)}",
            "username": m.group(1),
            "password": m.group(2),
        }

    async def _ensure_browser(self) -> bool:
        if self._browser is not None:
            try:
                if self._browser.is_connected():
                    return True
            except Exception:
                pass
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        try:
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=True,
                proxy=self._proxy_arg(),
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            logger.info("bet365 browser launched (proxy=%s)", "yes" if US_PROXY_URL else "no")
            return True
        except Exception as e:
            logger.error("Failed to launch bet365 browser: %s", e)
            self._browser = None
            return False

    async def _prime_once(self) -> bool:
        """Open the bet365 NJ landing page, harvest cookies, store in self.jar."""
        if not self._available:
            return False

        ok = await self._ensure_browser()
        if not ok:
            return False

        ctx = None
        try:
            ctx = await self._browser.new_context(
                user_agent=UA,
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
            page = await ctx.new_page()
            # Same stealth suite as DK \u2014 patches navigator.webdriver, plugins,
            # languages, vendor, WebGL fingerprint, chrome.* objects,
            # iframe.contentWindow, and UA HeadlessChrome strip.
            await page.add_init_script(_STEALTH_JS)
            await page.goto(PRIME_URL, wait_until="domcontentloaded", timeout=45000)
            # Cloudflare's bot check is fast (no challenge.js iframe to wait
            # on like Caesars / hCaptcha sites); 6s is plenty for __cf_bm to
            # land plus bet365's own pstk/swt session bootstrap.
            await page.wait_for_timeout(6000)
            try:
                await page.evaluate("window.scrollTo(0,400)")
                await page.wait_for_timeout(1500)
            except Exception:
                pass

            cookies = await ctx.cookies()
            new_jar: Dict[str, str] = {}
            for c in cookies:
                if "bet365" in (c.get("domain") or ""):
                    new_jar[c["name"]] = c["value"]

            # Sanity check \u2014 we need at least __cf_bm + one bet365-issued auth
            # cookie. pstk is the most reliable indicator of a real session.
            if "__cf_bm" not in new_jar or "pstk" not in new_jar:
                logger.warning(
                    "bet365 prime missing key cookies (got %s), keeping old jar",
                    list(new_jar.keys())[:8],
                )
                return False

            self.jar = new_jar
            self.last_prime_ts = time.time()
            self.ready = True
            logger.info(
                "bet365 cookie jar primed: %d cookies (cf+bet365 session present)",
                len(new_jar),
            )
            return True
        except Exception as e:
            logger.exception("bet365 prime failed: %s", e)
            return False
        finally:
            if ctx is not None:
                try:
                    await ctx.close()
                except Exception:
                    pass

    async def prime(self, force: bool = False) -> bool:
        async with self._lock:
            if self.priming:
                return self.ready
            self.priming = True
        try:
            now = time.time()
            if not force and (now - self.last_prime_ts) < PRIME_INTERVAL_SEC and self.ready:
                return True
            return await self._prime_once()
        finally:
            self.priming = False

    async def get_jar(self) -> Dict[str, str]:
        if not self._available:
            return {}
        now = time.time()
        if not self.ready or (now - self.last_prime_ts) > COOKIE_TTL_SEC:
            await self.prime(force=True)
        return dict(self.jar)

    async def background_loop(self) -> None:
        if not self._available:
            logger.info("bet365 background loop skipped (Playwright unavailable)")
            return
        await self.prime(force=True)
        while True:
            try:
                await asyncio.sleep(PRIME_INTERVAL_SEC)
                await self.prime(force=True)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("bet365 background loop error: %s", e)
                await asyncio.sleep(60)

    def start_background(self) -> None:
        if self._task is None or self._task.done():
            try:
                loop = asyncio.get_event_loop()
                self._task = loop.create_task(self.background_loop())
                logger.info("bet365 background priming task started")
            except Exception as e:
                logger.error("Could not start bet365 background loop: %s", e)

    async def shutdown(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except Exception:
                pass
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass


# Module-level singleton
_session = B365Session()


async def get_jar() -> Dict[str, str]:
    return await _session.get_jar()


async def prime(force: bool = False) -> bool:
    return await _session.prime(force=force)


def start_background() -> None:
    _session.start_background()


async def shutdown() -> None:
    await _session.shutdown()


def status() -> dict:
    return {
        "ready": _session.ready,
        "available": _session._available,
        "last_prime_ts": _session.last_prime_ts,
        "age_sec": int(time.time() - _session.last_prime_ts) if _session.last_prime_ts else None,
        "cookie_count": len(_session.jar),
        "priming": _session.priming,
        "prime_url": PRIME_URL,
    }
