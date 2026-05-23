"""
Recon script — capture all network calls FanDuel makes when navigating to a
soccer competition page. Prints unique sbapi.* request URLs.

Run: python sb-api/scripts/recon/fd_soccer_recon.py
"""
import asyncio
import json
import re
from collections import OrderedDict

from playwright.async_api import async_playwright


TARGETS = [
    ("EPL homepage",   "https://sportsbook.fanduel.com/navigation/soccer"),
    ("EPL competition","https://sportsbook.fanduel.com/football/competition/10932509"),
    ("MLS competition","https://sportsbook.fanduel.com/football/competition/12086600"),
]


async def capture(label: str, url: str, ms: int = 8000) -> list:
    """Open `url`, wait `ms` ms, return list of unique sbapi.* request URLs."""
    seen = OrderedDict()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = await ctx.new_page()

        def _on_request(req):
            u = req.url
            if "sbapi" in u and "fanduel.com" in u:
                # strip _ak query for cleanliness
                u_clean = re.sub(r"&?_ak=[^&]+", "", u)
                seen[u_clean] = req.method

        page.on("request", _on_request)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        except Exception as e:
            print(f"  [warn] navigation: {e}")

        await page.wait_for_timeout(ms)
        await browser.close()
    return list(seen.items())


async def main():
    for label, url in TARGETS:
        print(f"\n=== {label}: {url} ===")
        calls = await capture(label, url, ms=10000)
        print(f"  {len(calls)} sbapi calls")
        for u, m in calls[:30]:
            print(f"  [{m}] {u}")


if __name__ == "__main__":
    asyncio.run(main())
