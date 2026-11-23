# src/repair_data.py
"""
repair_data.py — Rewrite the committed CSVs through the same sanitiser the
fetcher uses, then report exactly what changed.

Typical use: the repository carried history from the old vnstock/VCI pipeline,
which contained a phantom Saturday bar in VNINDEX (2008-08-16) and dozens of
bars whose close sat outside their own low/high range. Running this once leaves
the committed data consistent, and the fetcher keeps it that way afterwards.

Chạy: python src/repair_data.py [--dry-run] [--symbols VNINDEX,VN30]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Dict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

import data_quality as dq

log = logging.getLogger("repair")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
SKIP_FILES = {"all_close.csv"}


def repair_file(path: str, dry_run: bool = False) -> Dict[str, object]:
    name = os.path.basename(path)
    frame = pd.read_csv(path, parse_dates=["time"], encoding="utf-8-sig")
    symbol = str(frame["symbol"].iloc[0]) if "symbol" in frame.columns and len(frame) else name[:-4]
    label = str(frame["name"].iloc[0]) if "name" in frame.columns and len(frame) else symbol

    rows, issues = dq.sanitize_bars(dq.frame_to_rows(frame), repair_ohlc=True)
    cleaned = dq.bars_to_frame(rows, symbol, label)
    # Compare serialised output, not dtypes: pandas infers different datetime
    # resolutions from a CSV than from python date objects.
    changed = len(cleaned) != len(frame) or cleaned.to_csv(index=False) != frame[
        cleaned.columns
    ].to_csv(index=False)

    counts = dq.summarize_issues(issues)["counts"]
    if changed and not dry_run:
        text = cleaned.to_csv(index=False)
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            handle.write(text)

    return {
        "file": name,
        "before": len(frame),
        "after": len(cleaned),
        "changed": changed,
        "counts": counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Làm sạch dữ liệu CSV đã commit")
    parser.add_argument("--dry-run", action="store_true", help="chỉ báo cáo, không ghi file")
    parser.add_argument("--symbols", default="", help="giới hạn mã, phân cách bằng dấu phẩy")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    wanted = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}

    results = []
    for name in sorted(os.listdir(DATA_DIR)):
        if not name.endswith(".csv") or name in SKIP_FILES:
            continue
        if wanted and name[:-4].upper() not in wanted:
            continue
        results.append(repair_file(os.path.join(DATA_DIR, name), dry_run=args.dry_run))

    changed = [r for r in results if r["changed"]]
    for row in changed:
        log.info(
            "%-14s %5d → %5d dòng  %s",
            row["file"],
            row["before"],
            row["after"],
            row["counts"] or "",
        )
    log.info(
        "%d/%d file %s. Tổng dòng bị loại: %d",
        len(changed),
        len(results),
        "cần sửa (dry-run)" if args.dry_run else "đã sửa",
        sum(int(r["before"]) - int(r["after"]) for r in results),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
