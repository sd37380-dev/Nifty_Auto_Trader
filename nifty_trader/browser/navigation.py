"""
Navigation utilities and security policy enforcement.
"""

from urllib.parse import urlparse
from nifty_trader.browser.errors import SecurityViolationError
from nifty_trader.browser.models import SourceType

# Known domains mapped to SourceType
SOURCE_DOMAIN_MAP = {
    "tradingview.com": SourceType.CHART,
    "in.tradingview.com": SourceType.CHART,
    "nseindia.com": SourceType.NSE,
    "moneycontrol.com": SourceType.NEWS,
    "economictimes.indiatimes.com": SourceType.NEWS,
    "livemint.com": SourceType.NEWS,
    "reuters.com": SourceType.NEWS,
    "bloomberg.com": SourceType.NEWS,
    "google.com": SourceType.SEARCH,
    "duckduckgo.com": SourceType.SEARCH,
}

ALLOWED_SCHEMES = {"http", "https", "about"}
FORBIDDEN_SCHEMES = {"file", "javascript", "data", "vbscript"}


def validate_url(url: str) -> str:
    """
    Validates URL safety. Prevents security exploits like file:// or javascript: injection.
    """
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()

    if scheme in FORBIDDEN_SCHEMES:
        raise SecurityViolationError(f"Navigation to URI scheme '{scheme}://' is strictly prohibited.")

    if scheme not in ALLOWED_SCHEMES:
        raise SecurityViolationError(f"Unsupported URL scheme '{scheme}'. Only http:// and https:// are permitted.")

    return url.strip()


def classify_source_type(url: str) -> SourceType:
    """
    Classifies the website category based on domain.
    """
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()

        for domain, st in SOURCE_DOMAIN_MAP.items():
            if hostname == domain or hostname.endswith(f".{domain}"):
                return st

        if "chart" in parsed.path.lower() or "chart" in hostname:
            return SourceType.CHART

        return SourceType.GENERAL_WEB
    except Exception:
        return SourceType.UNKNOWN
