"""
US Sportsbook Proxy Helper.

Allows US-region scrapers (DraftKings, FanDuel, BetRivers, ESPN, etc.) to be
routed through a US residential/datacenter proxy when the API is deployed
outside the US.

Set environment variables:
    US_PROXY_URL     - e.g. http://user:pass@proxy.example.com:22225
    UK_PROXY_URL     - e.g. http://user:pass@uk-proxy.example.com:22225
    EU_PROXY_URL     - (optional) for region-restricted EU books
    AU_PROXY_URL     - (optional) for region-restricted AU books
    DEFAULT_PROXY_URL - (optional) fallback for any region

When no proxy is set for a region, requests go direct (current behavior).

Usage:
    from ._proxy import get_client_kwargs

    async with httpx.AsyncClient(**get_client_kwargs(region="US")) as client:
        ...

    # For curl_cffi:
    from ._proxy import get_proxies_dict
    r = requests.get(url, impersonate="chrome", proxies=get_proxies_dict("US"))
"""
import os
from typing import Dict, Optional

_PROXY_ENV_MAP = {
    "US": "US_PROXY_URL",
    "UK": "UK_PROXY_URL",
    "GB": "UK_PROXY_URL",
    "EU": "EU_PROXY_URL",
    "AU": "AU_PROXY_URL",
    "NZ": "AU_PROXY_URL",
}


def get_proxy_url(region: str = "US") -> Optional[str]:
    """Return the proxy URL for a given region, or None if not configured."""
    region = (region or "US").upper()
    env_key = _PROXY_ENV_MAP.get(region, "DEFAULT_PROXY_URL")
    return os.getenv(env_key) or os.getenv("DEFAULT_PROXY_URL")


def get_proxies_dict(region: str = "US") -> Optional[Dict[str, str]]:
    """Return a proxies dict for requests/curl_cffi, or None if not configured."""
    url = get_proxy_url(region)
    if not url:
        return None
    return {"http": url, "https": url}


def get_client_kwargs(region: str = "US") -> Dict:
    """Return kwargs for httpx.AsyncClient with proxy configured for region."""
    url = get_proxy_url(region)
    if not url:
        return {}
    # httpx uses a single 'proxy' parameter in recent versions, 'proxies' in older
    try:
        import httpx
        if hasattr(httpx, "__version__"):
            major = int(httpx.__version__.split(".")[0])
            minor = int(httpx.__version__.split(".")[1])
            if (major, minor) >= (0, 26):
                return {"proxy": url}
    except Exception:
        pass
    return {"proxies": {"http://": url, "https://": url}}


def is_us_proxy_configured() -> bool:
    return bool(get_proxy_url("US"))


def proxy_status() -> Dict[str, bool]:
    """Return status of all proxy regions."""
    return {
        "US":  bool(get_proxy_url("US")),
        "UK":  bool(get_proxy_url("UK")),
        "EU":  bool(get_proxy_url("EU")),
        "AU":  bool(get_proxy_url("AU")),
        "default": bool(os.getenv("DEFAULT_PROXY_URL")),
    }