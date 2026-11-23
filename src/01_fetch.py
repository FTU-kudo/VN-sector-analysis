# src/01_fetch.py
"""
01_fetch.py — Daily OHLCV for the tracked Vietnamese indices.

Data source: the licensed market-data API reached through yuanta_client.py.
vnstock / VCI is no longer used anywhere in this repository.

Guarantees
----------
* history is appended, never blindly overwritten: a 15-day overlap is re-fetched
  so late corrections land, and a source that suddenly returns older data than
  the cache is rejected instead of committed.
* every bar passes data_quality.sanitize_bars, so weekend rows, partial sessions
  and impossible OHLC never reach the indicators.
* data/quality_report.json records what was repaired or rejected on each run.
* files are rewritten only when their bytes change (keeps git history clean).

Chạy: python src/01_fetch.py [--force-full] [--symbols VNINDEX,VN30]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

import data_quality as dq
import yuanta_client as yc

log = logging.getLogger("fetch")

# ── Cấu hình ────────────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)

HISTORY_START = date(2000, 1, 1)
OVERLAP_DAYS = 15
REPAIR_OHLC = os.environ.get("REPAIR_OHLC", "1") != "0"
STALE_WARN_DAYS = int(os.environ.get("STALE_WARN_DAYS", "5"))

QUALITY_PATH = os.path.join(DATA_DIR, "quality_report.json")

# Trạng thái lần chạy gần nhất (main.py đọc để cảnh báo).
LAST_RUN: Dict[str, Any] = {}

INDICES: Dict[str, str] = {
    # Chỉ số thị trường chung
    "VNINDEX": "VN-Index",
    "VN30": "VN30",
    "VN100": "VN100",
    "VNALL": "VN All Share",
    "HNXINDEX": "HNX-Index",
    "UPCOMINDEX": "UPCOM-Index",
    # Vốn hoá trung – nhỏ
    "VNMID": "VN Mid Cap",
    "VNSML": "VN Small Cap",
    # Ngành
    "VNFIN": "Tài chính",
    "VNREAL": "Bất động sản",
    "VNIT": "Công nghệ thông tin",
    "VNHEAL": "Y tế",
    "VNENE": "Năng lượng",
    "VNIND": "Công nghiệp",
    "VNMAT": "Nguyên vật liệu",
    "VNCONS": "Tiêu dùng thiết yếu",
    "VNCOND": "Tiêu dùng tùy ý",
    "VNUTI": "Tiện ích",
}


# ── Cache I/O ───────────────────────────────────────────────────
def cache_path(symbol: str) -> str:
    return os.path.join(DATA_DIR, f"{symbol}.csv")


def read_cache(symbol: str) -> Optional[pd.DataFrame]:
    path = cache_path(symbol)
    if not os.path.exists(path):
        return None
    try:
        frame = pd.read_csv(path, parse_dates=["time"], encoding="utf-8-sig")
    except Exception as exc:  # noqa: BLE001 - a broken cache must not stop the run
        log.error("%s: cache unreadable (%s) — sẽ tải lại toàn bộ", symbol, exc)
        return None
    if frame.empty or "time" not in frame.columns:
        return None
    for column in ("open", "high", "low", "close", "volume"):
        if column not in frame.columns:
            log.error("%s: cache thiếu cột %s — sẽ tải lại", symbol, column)
            return None
    return frame


def write_cache(symbol: str, frame: pd.DataFrame) -> bool:
    """Write only when the bytes differ. Returns True if the file changed."""
    path = cache_path(symbol)
    text = frame.to_csv(index=False)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            if handle.read() == text:
                return False
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        handle.write(text)
    return True


def _cache_needs_repair(
    frame: Optional[pd.DataFrame], now: Optional[datetime] = None
) -> bool:
    if frame is None or frame.empty:
        return False
    rows, issues = dq.sanitize_bars(
        dq.frame_to_rows(frame), now=now, repair_ohlc=REPAIR_OHLC
    )
    return bool(issues) or len(rows) != len(frame)


# ── Fetch một chỉ số ────────────────────────────────────────────
def fetch_one(
    symbol: str,
    name: str,
    client: yc.YuantaClient,
    force_full: bool = False,
    now: Optional[datetime] = None,
) -> Tuple[Optional[pd.DataFrame], Dict[str, Any]]:
    meta: Dict[str, Any] = {
        "status": "ok",
        "rows": 0,
        "latest": None,
        "requested_from": None,
        "fetched_bars": 0,
        "new_bars": 0,
        "issues": {"counts": {}, "samples": {}},
    }

    old = read_cache(symbol)
    all_issues: List[Dict[str, Any]] = []

    # Self-heal: a cache written by older code may still carry weekend rows or
    # broken OHLC. Cleaning on load is idempotent and logged.
    if _cache_needs_repair(old, now=now):
        rows, cache_issues = dq.sanitize_bars(
            dq.frame_to_rows(old), now=now, repair_ohlc=REPAIR_OHLC
        )
        all_issues.extend(cache_issues)
        log.info(
            "  🧹 %s: dọn cache %d → %d dòng (%d vấn đề)",
            f"{symbol:12s}",
            len(old),
            len(rows),
            len(cache_issues),
        )
        old = dq.bars_to_frame(rows, symbol, name) if rows else None

    old_latest = (
        pd.to_datetime(old["time"]).max().date()
        if old is not None and not old.empty
        else None
    )

    full = force_full or old is None
    start = HISTORY_START if full else old_latest - timedelta(days=OVERLAP_DAYS)
    meta["requested_from"] = start.isoformat()
    log.info(
        "  %s %-22s (%s) từ %s",
        "⬇️  tải toàn bộ" if full else "🔄 cập nhật  ",
        name,
        symbol,
        start,
    )

    try:
        bars = client.history(symbol, start)
    except yc.YuantaError as exc:
        log.error("  ❌ %-22s (%s): %s — giữ cache cũ", name, symbol, exc)
        meta["status"] = "failed"
        meta["error"] = str(exc)[:300]
        if old is not None and not old.empty:
            meta["rows"] = len(old)
            meta["latest"] = old_latest.isoformat()
            meta["issues"] = dq.summarize_issues(all_issues)
            return old, meta
        meta["issues"] = dq.summarize_issues(all_issues)
        return None, meta

    meta["fetched_bars"] = len(bars)
    rows, fresh_issues = dq.sanitize_bars(bars, now=now, repair_ohlc=REPAIR_OHLC)
    all_issues.extend(fresh_issues)
    meta["issues"] = dq.summarize_issues(all_issues)

    fresh = dq.bars_to_frame(rows, symbol, name)
    merged = dq.merge_frames(old, fresh)

    if merged.empty:
        log.error("  ❌ %-22s (%s): không có dữ liệu dùng được", name, symbol)
        meta["status"] = "empty"
        return None, meta

    latest = pd.to_datetime(merged["time"]).max().date()

    # Merging can only ever extend history, so the cache cannot be rolled back.
    # If the source itself lags behind the cache, say so loudly: it means the
    # feed is broken, not that the data is complete.
    fresh_latest = (
        pd.to_datetime(fresh["time"]).max().date() if not fresh.empty else None
    )
    if old_latest is not None and fresh_latest is not None and fresh_latest < old_latest:
        log.warning(
            "  ⚠️  %-22s (%s): nguồn chỉ có tới %s, cache tới %s — giữ cache",
            name,
            symbol,
            fresh_latest,
            old_latest,
        )
        meta["status"] = "behind"
        meta["source_latest"] = fresh_latest.isoformat()

    meta["new_bars"] = (
        int((pd.to_datetime(merged["time"]) > pd.Timestamp(old_latest)).sum())
        if old_latest
        else len(merged)
    )
    meta["rows"] = len(merged)
    meta["latest"] = latest.isoformat()

    changed = write_cache(symbol, merged)
    log.info(
        "  %s %-22s (%s) %4d phiên [%s → %s] %s",
        "✅" if changed else "⚡",
        name,
        symbol,
        len(merged),
        pd.to_datetime(merged["time"]).min().date(),
        latest,
        f"+{meta['new_bars']} mới" if changed else "không đổi",
    )
    return merged, meta


# ── Kiểm tra chéo với bảng chỉ số ───────────────────────────────
def board_check(
    client: yc.YuantaClient, frames: Dict[str, pd.DataFrame]
) -> Dict[str, Any]:
    """Informational cross-check of our last close against the index board.

    The board is optional: if it is blocked or reshaped, the run continues.
    """
    try:
        rows = client.index_board()
    except yc.YuantaError as exc:
        log.warning("Bảng chỉ số không dùng được (%s) — bỏ qua kiểm tra chéo", exc)
        return {"available": False, "error": str(exc)[:200]}

    board = {str(r.get("IndexCode", "")).upper(): r for r in rows if r.get("IndexCode")}
    checks: Dict[str, Any] = {}
    for symbol, frame in frames.items():
        row = board.get(symbol)
        if row is None:
            checks[symbol] = {"on_board": False}
            continue
        closes = pd.to_numeric(frame["close"], errors="coerce").dropna()
        entry: Dict[str, Any] = {
            "on_board": True,
            "session": str(row.get("CurrTradingSessionID", "")),
            "last_close": round(float(closes.iloc[-1]), 2) if len(closes) else None,
            "ref": row.get("RefIndex"),
            "curr": row.get("CurrIndex"),
        }
        try:
            entry["delta_vs_ref_pct"] = round((float(entry["last_close"]) / float(row["RefIndex"]) - 1) * 100, 3)
        except (TypeError, ValueError, ZeroDivisionError, KeyError):
            pass
        checks[symbol] = entry

    missing = sorted(s for s, c in checks.items() if not c.get("on_board"))
    if missing:
        log.warning("Không thấy trên bảng chỉ số: %s", ", ".join(missing))
    return {"available": True, "indexes": checks}


# ── Toàn bộ ─────────────────────────────────────────────────────
def fetch_all(
    symbols: Optional[List[str]] = None, force_full: bool = False
) -> Dict[str, pd.DataFrame]:
    log.info("=" * 64)
    log.info("  FETCH: %d chỉ số VN  (nguồn: %s)", len(INDICES), yc.base_url())
    log.info("=" * 64)

    client = yc.YuantaClient()
    unknown = [s for s in (symbols or []) if s not in INDICES]
    if unknown:
        log.warning("Bỏ qua mã không theo dõi: %s", ", ".join(unknown))
    targets = [s for s in INDICES if symbols is None or s in symbols]

    results: Dict[str, pd.DataFrame] = {}
    report: Dict[str, Any] = {}

    for symbol in targets:
        frame, meta = fetch_one(symbol, INDICES[symbol], client, force_full=force_full)
        report[symbol] = meta
        if frame is not None:
            results[symbol] = frame

    # ── Pivot giá đóng cửa ──────────────────────────────────────
    if results:
        close_wide = pd.concat(results.values()).pivot_table(
            index="time", columns="symbol", values="close", aggfunc="last"
        )
        close_wide = close_wide[[s for s in INDICES if s in close_wide.columns]]
        path = os.path.join(DATA_DIR, "all_close.csv")
        text = close_wide.to_csv()
        if not os.path.exists(path):
            previous = None
        else:
            with open(path, "r", encoding="utf-8-sig", newline="") as handle:
                previous = handle.read()
        if previous != text:
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                handle.write(text)
            log.info("Đã cập nhật data/all_close.csv (%d dòng)", len(close_wide))

    # ── Chất lượng & độ mới ─────────────────────────────────────
    latest_session = max(
        (pd.to_datetime(f["time"]).max().date() for f in results.values()), default=None
    )
    stale_days = (yc.vn_now().date() - latest_session).days if latest_session else None

    issue_counts = {
        symbol: meta["issues"]["counts"] for symbol, meta in report.items() if meta["issues"]["counts"]
    }
    total_issues = sum(sum(c.values()) for c in issue_counts.values())

    report_meta: Dict[str, Any] = {
        "generated_at": yc.vn_now().isoformat(timespec="seconds"),
        "source_host": yc.base_url(),
        "repair_ohlc": REPAIR_OHLC,
        "latest_session": latest_session.isoformat() if latest_session else None,
        "stale_days": stale_days,
        "issue_count": total_issues,
        "issue_counts": issue_counts,
        "symbols": report,
        "request_stats": dict(client.stats),
    }
    report_meta["board_check"] = board_check(client, results)

    with open(QUALITY_PATH, "w", encoding="utf-8") as handle:
        json.dump(report_meta, handle, ensure_ascii=False, indent=1, sort_keys=True)
        handle.write("\n")

    if stale_days is not None and stale_days > STALE_WARN_DAYS:
        log.warning(
            "⚠️  Phiên mới nhất là %s — cũ %d ngày. Kiểm tra nguồn dữ liệu.",
            latest_session,
            stale_days,
        )

    failed = sorted(s for s, m in report.items() if m["status"] in ("failed", "empty"))
    if failed:
        log.error("Không lấy được: %s", ", ".join(failed))
    log.info(
        "Xong: %d/%d chỉ số, phiên mới nhất %s, %d vấn đề dữ liệu đã xử lý",
        len(results),
        len(targets),
        latest_session,
        total_issues,
    )

    LAST_RUN.clear()
    LAST_RUN.update(
        {
            "symbols_ok": len(results),
            "symbols_total": len(targets),
            "failed": failed,
            "latest_session": latest_session.isoformat() if latest_session else None,
            "stale_days": stale_days,
            "quality_report": QUALITY_PATH,
        }
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Tải OHLCV chỉ số từ nguồn dữ liệu đã mua")
    parser.add_argument("--force-full", action="store_true", help="tải lại toàn bộ lịch sử")
    parser.add_argument("--symbols", default="", help="danh sách mã, phân cách bằng dấu phẩy")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)-10s %(message)s"
    )
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    frames = fetch_all(symbols=symbols or None, force_full=args.force_full)
    return 0 if frames else 2


if __name__ == "__main__":
    sys.exit(main())
