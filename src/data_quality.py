# src/data_quality.py
"""
data_quality.py — validation, repair and merge rules for daily bars.

Every bar that enters a CSV passes through here, so a bad upstream row can no
longer reach the indicators silently. Repairs are always recorded and surfaced
in data/quality_report.json.

Rules
-----
* non-numeric / non-positive OHLC          -> row dropped
* weekend date                             -> row dropped (VN exchanges are Mon-Fri)
* date in the future                       -> row dropped
* today's bar before 15:15 Vietnam time    -> row dropped (partial session)
* close outside [low, high]                -> high/low widened to bracket it
* duplicate date                           -> newest copy wins
* unsorted                                 -> sorted ascending
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

VN_TZ = timezone(timedelta(hours=7))
SESSION_CLOSE = time(15, 15)

ISSUE_CODES = (
    "bad_values",
    "weekend",
    "future",
    "partial_session",
    "ohlc_repaired",
    "open_clipped",
    "ohlc_skipped",
    "duplicate",
    "empty",
)

MAX_SAMPLES_PER_CODE = 25


def _issue(code: str, day: Optional[date], detail: str = "") -> Dict[str, Any]:
    return {
        "code": code,
        "date": day.isoformat() if isinstance(day, date) else None,
        "detail": detail,
    }


def sanitize_bars(
    bars: Iterable[Dict[str, Any]],
    today: Optional[date] = None,
    now: Optional[datetime] = None,
    repair_ohlc: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (clean rows sorted by date, issues). Never raises on bad input."""
    now = now or datetime.now(VN_TZ)
    today = today or now.date()

    rows: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []

    for bar in bars:
        day = bar.get("date")
        if isinstance(day, str):
            try:
                day = date.fromisoformat(day)
            except ValueError:
                issues.append(_issue("bad_values", None, "unparsable date"))
                continue
        if not isinstance(day, date):
            issues.append(_issue("bad_values", None, "missing date"))
            continue

        try:
            o = float(bar["open"])
            h = float(bar["high"])
            l = float(bar["low"])
            c = float(bar["close"])
            v = float(bar.get("volume") or 0.0)
        except (KeyError, TypeError, ValueError):
            issues.append(_issue("bad_values", day, "non-numeric OHLC"))
            continue

        if any(x != x for x in (o, h, l, c, v)):  # NaN
            issues.append(_issue("bad_values", day, "NaN in OHLC"))
            continue
        if min(o, h, l, c) <= 0:
            issues.append(_issue("bad_values", day, "non-positive price"))
            continue

        if day.weekday() >= 5:
            issues.append(_issue("weekend", day, "no session on weekends"))
            continue
        if day > today:
            issues.append(_issue("future", day, "date ahead of today"))
            continue
        if day == today and now.time() < SESSION_CLOSE:
            issues.append(_issue("partial_session", day, "session still open"))
            continue

        high, low = h, l
        if high < low:
            high, low = low, high

        # The close is the series everything depends on, so it is never altered:
        # if it sits outside the recorded range, the range is what is wrong.
        if c > high or c < low:
            if repair_ohlc:
                new_high = max(high, c)
                new_low = min(low, c)
                issues.append(
                    _issue(
                        "ohlc_repaired",
                        day,
                        f"low/high {low:g}/{high:g} -> {new_low:g}/{new_high:g} "
                        f"to include close {c:g}",
                    )
                )
                high, low = new_high, new_low
            else:
                issues.append(
                    _issue("ohlc_skipped", day, "close outside [low, high], repair disabled")
                )

        # In the upstream feed the open is sometimes carried over from the
        # previous session for several days while low/high/close keep moving
        # (e.g. VNFIN 2018-08-15..17 all opened at 839.63). The open is then the
        # unreliable field, so it is pulled back into the real range instead of
        # inflating high/low with a stale value.
        if o > high or o < low:
            if repair_ohlc:
                clipped = high if o > high else low
                issues.append(
                    _issue(
                        "open_clipped",
                        day,
                        f"open {o:g} outside [{low:g}, {high:g}] -> {clipped:g}",
                    )
                )
                o = clipped
            else:
                issues.append(
                    _issue("ohlc_skipped", day, "open outside [low, high], repair disabled")
                )

        rows.append(
            {
                "date": day,
                "open": o,
                "high": high,
                "low": low,
                "close": c,
                "volume": int(v) if v >= 0 else 0,
            }
        )

    # Newest copy of a date wins, then chronological order.
    deduped: Dict[date, Dict[str, Any]] = {}
    for row in rows:
        if row["date"] in deduped:
            issues.append(_issue("duplicate", row["date"], "newest copy kept"))
        deduped[row["date"]] = row

    clean = [deduped[d] for d in sorted(deduped)]
    if not clean:
        issues.append(_issue("empty", None, "no usable bars"))
    return clean, issues


def bars_to_frame(
    rows: Sequence[Dict[str, Any]], symbol: str, name: str = ""
) -> pd.DataFrame:
    """Rows -> the CSV schema the rest of the pipeline expects."""
    if not rows:
        return pd.DataFrame(
            columns=["time", "open", "high", "low", "close", "volume", "symbol", "name"]
        )
    frame = pd.DataFrame(rows)
    frame["time"] = pd.to_datetime(frame["date"])
    frame = frame.drop(columns=["date"])
    frame["volume"] = frame["volume"].astype("int64")
    frame["symbol"] = symbol
    frame["name"] = name
    return frame[
        ["time", "open", "high", "low", "close", "volume", "symbol", "name"]
    ].sort_values("time", ignore_index=True)


def merge_frames(old: Optional[pd.DataFrame], new: pd.DataFrame) -> pd.DataFrame:
    """Overlay freshly fetched bars on the cached history (new values win)."""
    if old is None or old.empty:
        return new.sort_values("time", ignore_index=True)
    if new is None or new.empty:
        return old.sort_values("time", ignore_index=True)
    merged = pd.concat([old, new], ignore_index=True)
    merged = merged.drop_duplicates(subset=["time"], keep="last")
    return merged.sort_values("time", ignore_index=True)


def frame_to_rows(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    """DataFrame -> bar dicts (used by the repair CLI and by tests)."""
    rows: List[Dict[str, Any]] = []
    for rec in frame.to_dict("records"):
        stamp = rec.get("time")
        day = stamp.date() if isinstance(stamp, (datetime, pd.Timestamp)) else stamp
        if not isinstance(day, date):
            continue
        rows.append(
            {
                "date": day,
                "open": rec.get("open"),
                "high": rec.get("high"),
                "low": rec.get("low"),
                "close": rec.get("close"),
                "volume": rec.get("volume"),
            }
        )
    return rows


def summarize_issues(issues: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Counts by code plus a bounded sample, for quality_report.json."""
    counts: Dict[str, int] = {}
    samples: Dict[str, List[Dict[str, str]]] = {}
    for item in issues:
        code = item.get("code", "unknown")
        counts[code] = counts.get(code, 0) + 1
        bucket = samples.setdefault(code, [])
        if len(bucket) < MAX_SAMPLES_PER_CODE:
            bucket.append(
                {"date": item.get("date"), "detail": item.get("detail", "")}
            )
    return {"counts": counts, "samples": samples}
