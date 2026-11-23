# src/yuanta_client.py
"""
yuanta_client.py — HTTP client for the licensed market-data endpoints.

Replaces vnstock entirely. Only the two public read-only endpoints documented
in the project handoff are used:

  * /v2/tradingview/history            -> daily OHLCV bars (stocks and indexes)
  * /api/v3/market_data/price_board/index/list_index  -> index board snapshot

Behaviour that matters (learned from production runs):

  * `t` in a bar is 00:00 UTC of the trade date, so the trading date must be
    derived in UTC, never in local time.
  * `to=<now>` does NOT return the current session; a `to` two days ahead does.
  * From CI runner IPs the edge sometimes answers `200 text/html` with
    "Attention Required" and a `window.location.href = "<same url>?jskey=..."`
    bounce. We follow that bounce (same host only, bounded hops) inside one
    cookie-carrying session.

No credentials are required by these endpoints. The host can be overridden with
YUANTA_BASE_URL if it ever moves.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin, urlparse

import requests

log = logging.getLogger("yuanta")

# Vietnam has no DST, so a fixed offset is exact and needs no tzdata.
VN_TZ = timezone(timedelta(hours=7))
UTC = timezone.utc

DEFAULT_BASE_URL = "https://ysradar.yuanta.com.vn"
ALLOWED_HOSTS = frozenset({"ysradar.yuanta.com.vn", "ysradarapi.yuanta.com.vn"})

HISTORY_PATH = "/v2/tradingview/history"
INDEX_LIST_PATH = "/api/v3/market_data/price_board/index/list_index"

DEFAULT_TIMEOUT = (10, 30)
MAX_CHALLENGE_HOPS = 3

# Markers of the HTML interstitial served to datacentre IPs.
_CHALLENGE_MARKERS = (
    "attention required",
    "window.location.href",
    "cf-browser-verification",
    "just a moment",
    "checking your browser",
)
_LOCATION_RE = re.compile(
    r"""window\.location(?:\.href)?\s*=\s*["']([^"']+)["']""", re.IGNORECASE
)
_REPLACE_RE = re.compile(
    r"""location\.replace\(\s*["']([^"']+)["']\s*\)""", re.IGNORECASE
)


class YuantaError(RuntimeError):
    """Any unrecoverable problem talking to the data source."""


class ChallengeError(YuantaError):
    """The anti-bot interstitial could not be resolved."""


def base_url() -> str:
    return os.environ.get("YUANTA_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def vn_now() -> datetime:
    return datetime.now(VN_TZ)


def future_to_epoch(days_ahead: int = 2) -> int:
    """`to` value that reliably includes the latest finished session."""
    target = datetime.combine(
        vn_now().date() + timedelta(days=days_ahead), datetime.min.time(), tzinfo=VN_TZ
    )
    return int(target.timestamp())


def start_to_epoch(start: date) -> int:
    """`from` value inclusive of `start`.

    Bars are stamped 00:00 UTC, so we step one day back and let the sanitiser
    de-duplicate rather than risk dropping the first session.
    """
    return int(datetime.combine(start, datetime.min.time(), tzinfo=UTC).timestamp()) - 86400


def _json_or_none(resp: requests.Response) -> Optional[Any]:
    try:
        return resp.json()
    except ValueError:
        return None


def is_challenge(resp: requests.Response) -> bool:
    """True when the body is the HTML interstitial instead of JSON."""
    if _json_or_none(resp) is not None:
        return False
    ctype = (resp.headers.get("Content-Type") or "").lower()
    body = (resp.text or "")[:8000]
    lowered = body.lower()
    if any(marker in lowered for marker in _CHALLENGE_MARKERS):
        return True
    return "html" in ctype


def extract_next_url(resp_or_body: Any, current_url: str) -> Optional[str]:
    """Pull the bounce target out of the interstitial, same-host only."""
    body = (
        resp_or_body
        if isinstance(resp_or_body, str)
        else (getattr(resp_or_body, "text", "") or "")
    )
    match = _LOCATION_RE.search(body) or _REPLACE_RE.search(body)
    if not match:
        return None
    target = urljoin(current_url, match.group(1).strip())
    parsed = urlparse(target)
    if parsed.scheme not in ("http", "https"):
        return None
    if parsed.hostname not in ALLOWED_HOSTS:
        log.warning("Refusing challenge bounce to foreign host %r", parsed.hostname)
        return None
    return target


class YuantaClient:
    """Small, defensive JSON client with session cookies and bounded retries."""

    def __init__(
        self,
        base: Optional[str] = None,
        timeout: tuple = DEFAULT_TIMEOUT,
        retries: int = 3,
        backoff: float = 2.0,
        session: Optional[requests.Session] = None,
        sleep: Any = time.sleep,
    ) -> None:
        self.base = (base or base_url()).rstrip("/")
        self.timeout = timeout
        self.retries = max(1, retries)
        self.backoff = backoff
        self.session = session if session is not None else requests.Session()
        self._sleep = sleep
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
                "Referer": self.base + "/",
            }
        )
        self.stats: Dict[str, int] = {"requests": 0, "challenges": 0, "retries": 0}

    # ── transport ────────────────────────────────────────────────────
    def _raw_get(self, url: str, params: Optional[dict] = None) -> requests.Response:
        self.stats["requests"] += 1
        return self.session.get(url, params=params, timeout=self.timeout)

    def _resolve_challenge(self, resp: requests.Response, url: str) -> requests.Response:
        """Follow the ?jskey bounce up to MAX_CHALLENGE_HOPS times."""
        hops = 0
        while is_challenge(resp) and hops < MAX_CHALLENGE_HOPS:
            nxt = extract_next_url(resp, url)
            if not nxt:
                break
            hops += 1
            self.stats["challenges"] += 1
            log.info("Anti-bot interstitial, following hop %d", hops)
            url = nxt
            resp = self._raw_get(url)
        if is_challenge(resp):
            raise ChallengeError(
                "Data source returned an HTML interstitial instead of JSON "
                f"(status {resp.status_code}) after {hops} bounce(s)"
            )
        return resp

    def get_json(self, path: str, params: Optional[dict] = None, what: str = "") -> Any:
        url = path if path.startswith("http") else self.base + path
        label = what or path
        last_error: Optional[Exception] = None

        for attempt in range(1, self.retries + 1):
            try:
                resp = self._raw_get(url, params)
                resp = self._resolve_challenge(resp, url)
            except ChallengeError as exc:
                last_error = exc
            except requests.RequestException as exc:
                last_error = exc
            else:
                payload = _json_or_none(resp)
                if payload is not None:
                    if resp.status_code >= 400:
                        raise YuantaError(
                            f"{label}: HTTP {resp.status_code} with JSON body"
                        )
                    return payload
                if resp.status_code < 500 and resp.status_code != 429:
                    snippet = (resp.text or "")[:200].replace("\n", " ")
                    raise YuantaError(
                        f"{label}: HTTP {resp.status_code}, non-JSON body: {snippet!r}"
                    )
                last_error = YuantaError(f"{label}: HTTP {resp.status_code}")

            if attempt < self.retries:
                self.stats["retries"] += 1
                delay = self.backoff ** attempt
                log.warning(
                    "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                    label,
                    attempt,
                    self.retries,
                    last_error,
                    delay,
                )
                self._sleep(delay)

        raise YuantaError(f"{label}: giving up after {self.retries} attempts ({last_error})")

    # ── endpoints ────────────────────────────────────────────────────
    def history(
        self,
        symbol: str,
        start: date,
        end_epoch: Optional[int] = None,
        resolution: str = "1D",
    ) -> List[Dict[str, Any]]:
        """Daily bars as plain dicts: date, open, high, low, close, volume."""
        params = {
            "symbol": symbol,
            "resolution": resolution,
            "from": start_to_epoch(start),
            "to": end_epoch if end_epoch is not None else future_to_epoch(),
            "limit": 100000,
        }
        payload = self.get_json(HISTORY_PATH, params, what=f"history:{symbol}")
        return parse_history_payload(payload, symbol)

    def index_board(self) -> List[Dict[str, Any]]:
        """Snapshot rows from the index price board (may be empty on failure)."""
        payload = self.get_json(INDEX_LIST_PATH, what="index_board")
        rows: Iterable[Any]
        if isinstance(payload, dict):
            rows = payload.get("response") or []
        elif isinstance(payload, list):
            rows = payload
        else:
            rows = []
        return [r for r in rows if isinstance(r, dict)]


def _to_date(ts: Any) -> Optional[date]:
    """Trading date from a bar timestamp (seconds or milliseconds, UTC-based)."""
    try:
        value = int(ts)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    if value > 10_000_000_000:  # milliseconds
        value //= 1000
    try:
        return datetime.fromtimestamp(value, UTC).date()
    except (OverflowError, OSError, ValueError):
        return None


def _to_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def parse_history_payload(payload: Any, symbol: str = "") -> List[Dict[str, Any]]:
    """Turn a TradingView-style payload into clean bar dicts (unsanitised)."""
    if not isinstance(payload, dict):
        raise YuantaError(f"history:{symbol}: unexpected payload type {type(payload).__name__}")

    status = payload.get("s")
    if status in ("no_data", None) and not payload.get("bars"):
        if status == "no_data":
            log.info("history:%s has no data in range", symbol)
            return []
        raise YuantaError(f"history:{symbol}: payload without 's' or 'bars'")
    if status not in ("ok", "no_data"):
        raise YuantaError(f"history:{symbol}: status {status!r}")

    bars = payload.get("bars") or []
    if not isinstance(bars, list):
        raise YuantaError(f"history:{symbol}: 'bars' is not a list")

    out: List[Dict[str, Any]] = []
    skipped = 0
    for bar in bars:
        if not isinstance(bar, dict):
            skipped += 1
            continue
        day = _to_date(bar.get("t"))
        o = _to_float(bar.get("o"))
        h = _to_float(bar.get("h"))
        l = _to_float(bar.get("l"))
        c = _to_float(bar.get("c"))
        v = _to_float(bar.get("v")) or 0.0
        if day is None or None in (o, h, l, c):
            skipped += 1
            continue
        out.append(
            {"date": day, "open": o, "high": h, "low": l, "close": c, "volume": v}
        )

    if skipped:
        log.warning("history:%s skipped %d malformed bar(s)", symbol, skipped)
    out.sort(key=lambda r: r["date"])
    return out
