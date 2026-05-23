"""
DraftKings Akamai-bypass session manager.

DraftKings' public sportsbook is fronted by Akamai Bot Manager which blocks
all direct httpx/curl_cffi calls (returns 403 "Access Denied" — even from
clean residential IPs without a valid sensor-data cookie).

However, a real headless Chromium browser passes the Akamai challenge and
receives a valid cookie set (`_abck`, `bm_sz`, `STH`, `_dd_s`, ...). Once
we have that cookie jar, we can replay arbitrary XHR calls to
`sportsbook-nash.draftkings.com/sites/{site}/api/sportscontent/...` via
ordinary HTTP for 5+ minutes before the cookies expire.

This module:
  • Owns a single global Playwright browser instance.
  • Primes the cookie jar on startup and re-primes every PRIME_INTERVAL_SEC.
  • Exposes `get_jar()` for scrapers to read the current cookie dict.
  • Is fully optional — if Playwright import or chromium launch fails, the
    module sets `READY=False` and scrapers fall back to returning [].

Designed to be cheap: one priming costs ~10s of CPU and ~100MB RAM transiently.
We re-prime every 5 min by default, well within Akamai's cookie lifetime.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Dict, Optional

logger = logging.getLogger("dk_session")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Page used to prime cookies. Any DK sport page works; basketball/nba is
# always available year-round.
PRIME_URL = "https://sportsbook.draftkings.com/leagues/basketball/nba"

# Re-prime cookies at this interval. Akamai cookies typically last 10–30 min
# so 5 min gives a safe margin.
PRIME_INTERVAL_SEC = int(os.getenv("DK_PRIME_INTERVAL_SEC", "300"))

# How long after a prime we still consider cookies fresh enough to use.
# If a request would land outside this window we trigger a re-prime first.
COOKIE_TTL_SEC = int(os.getenv("DK_COOKIE_TTL_SEC", "420"))  # 7 min

US_PROXY_URL = os.getenv("US_PROXY_URL", "").strip()


class DKSession:
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
            logger.warning("Playwright unavailable, DK scraper will return []: %s", e)
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
        """Launch the global browser instance if not already running."""
        if self._browser is not None:
            try:
                if self._browser.is_connected():
                    return True
            except Exception:
                pass
            # browser is dead, rebuild
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
            logger.info("DK browser launched (proxy=%s)", "yes" if US_PROXY_URL else "no")
            return True
        except Exception as e:
            logger.error("Failed to launch DK browser: %s", e)
            self._browser = None
            return False

    async def _prime_once(self) -> bool:
        """Open DK page, harvest cookies, store in self.jar."""
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
            await page.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"
                "Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});"
                "window.chrome={runtime:{}};"
            )
            await page.goto(PRIME_URL, wait_until="domcontentloaded", timeout=45000)
            # Give Akamai's JS challenge time to run and set _abck cookie
            await page.wait_for_timeout(7000)
            try:
                await page.evaluate("window.scrollTo(0,800)")
                await page.wait_for_timeout(1500)
            except Exception:
                pass

            cookies = await ctx.cookies()
            new_jar: Dict[str, str] = {}
            for c in cookies:
                if "draftkings" in (c.get("domain") or ""):
                    new_jar[c["name"]] = c["value"]

            # Sanity check — Akamai cookies must be present
            if "_abck" not in new_jar or "bm_sz" not in new_jar:
                logger.warning("DK prime missing Akamai cookies (got %s), keeping old jar", list(new_jar.keys())[:8])
                return False

            self.jar = new_jar
            self.last_prime_ts = time.time()
            self.ready = True
            logger.info("DK cookie jar primed: %d cookies (key Akamai cookies present)", len(new_jar))
            return True
        except Exception as e:
            logger.exception("DK prime failed: %s", e)
            return False
        finally:
            if ctx is not None:
                try:
                    await ctx.close()
                except Exception:
                    pass

    async def prime(self, force: bool = False) -> bool:
        """Public API: prime if needed (or if force=True)."""
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
        """Get fresh cookie jar, re-priming if cookies are stale."""
        if not self._available:
            return {}
        now = time.time()
        if not self.ready or (now - self.last_prime_ts) > COOKIE_TTL_SEC:
            await self.prime(force=True)
        return dict(self.jar)

    async def background_loop(self) -> None:
        """Long-running task: prime once, then re-prime every PRIME_INTERVAL_SEC."""
        if not self._available:
            logger.info("DK background loop skipped (Playwright unavailable)")
            return
        # initial prime
        await self.prime(force=True)
        while True:
            try:
                await asyncio.sleep(PRIME_INTERVAL_SEC)
                await self.prime(force=True)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("DK background loop error: %s", e)
                await asyncio.sleep(60)

    def start_background(self) -> None:
        if self._task is None or self._task.done():
            try:
                loop = asyncio.get_event_loop()
                self._task = loop.create_task(self.background_loop())
                logger.info("DK background priming task started")
            except Exception as e:
                logger.error("Could not start DK background loop: %s", e)

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
_session = DKSession()


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
    }
