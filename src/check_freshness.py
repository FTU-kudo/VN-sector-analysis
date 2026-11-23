# src/check_freshness.py
"""
check_freshness.py — Fail the run when the stored data is older than the
business-day budget allows.

This is the guard that was missing while the bot sat dead for ten days with
every workflow red: the data date is now checked explicitly instead of being
inferred from a report that simply kept quoting its last successful session.

Two thresholds:
  * warn  (default 2 business days) — printed, exit 0
  * fail  (default 8 business days) — exit 1

Tết closes the market for about six business days, so the failure threshold sits
just above that: a Tết gap warns, a real outage fails.

Chạy: python src/check_freshness.py [--max-business-days 8] [--warn-business-days 2]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone

log = logging.getLogger("freshness")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
VN_TZ = timezone(timedelta(hours=7))
SKIP_FILES = {"all_close.csv"}


def latest_session(data_dir: str = DATA_DIR) -> date | None:
    """Newest bar date across the per-symbol CSVs (all_close is derived)."""
    newest: date | None = None
    for name in os.listdir(data_dir):
        if not name.endswith(".csv") or name in SKIP_FILES:
            continue
        path = os.path.join(data_dir, name)
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                header = handle.readline().strip().split(",")
                if "time" not in header:
                    continue
                index = header.index("time")
                last = None
                for line in handle:
                    if line.strip():
                        last = line
                if last is None:
                    continue
                stamp = last.split(",")[index].strip()[:10]
                day = datetime.strptime(stamp, "%Y-%m-%d").date()
        except (OSError, ValueError):
            log.warning("%s: không đọc được ngày cuối", name)
            continue
        if newest is None or day > newest:
            newest = day
    return newest


def business_days_between(start: date, end: date) -> int:
    """Number of Mon-Fri days strictly after `start` and up to `end`."""
    if end <= start:
        return 0
    days = 0
    cursor = start
    while cursor < end:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days += 1
    return days


def main() -> int:
    parser = argparse.ArgumentParser(description="Kiểm tra độ mới của dữ liệu")
    parser.add_argument("--max-business-days", type=int, default=8)
    parser.add_argument("--warn-business-days", type=int, default=2)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    today = datetime.now(VN_TZ).date()
    newest = latest_session()

    if newest is None:
        log.error("❌ Không tìm thấy dữ liệu ngày nào trong %s", DATA_DIR)
        return 1

    missed = business_days_between(newest, today)
    log.info("Phiên mới nhất: %s — hôm nay %s — thiếu %d ngày giao dịch", newest, today, missed)

    if missed > args.max_business_days:
        log.error(
            "❌ Dữ liệu cũ %d ngày giao dịch (ngưỡng %d). Nguồn dữ liệu có thể đã hỏng.",
            missed,
            args.max_business_days,
        )
        return 1
    if missed > args.warn_business_days:
        log.warning("⚠️  Dữ liệu cũ %d ngày giao dịch — kiểm tra lại nguồn.", missed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
