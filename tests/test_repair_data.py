# tests/test_repair_data.py
"""
test_repair_data.py — the one-off cleaner for committed CSVs, plus the
freshness guard that would have caught a ten-day outage.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta


def write_csv(path, rows, header="time,open,high,low,close,volume,symbol,name"):
    lines = [header] + rows
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path


# ── repair ────────────────────────────────────────────────────────
def test_repair_removes_weekend_row_and_repairs_ohlc(tmp_path, repair):
    path = write_csv(
        tmp_path / "VNINDEX.csv",
        [
            "2005-07-25,253.58,254.15,253.58,246.31,273820,VNINDEX,VN-Index",
            "2008-08-16,900.26,900.26,900.26,900.26,3582160,VNINDEX,VN-Index",
            "2026-11-09,1728.27,1728.27,1701.9,1714.32,678512401,VNINDEX,VN-Index",
        ],
    )
    result = repair.repair_file(str(path))

    assert result["changed"] is True
    assert result["before"] == 3
    assert result["after"] == 2
    text = path.read_text(encoding="utf-8-sig")
    assert "2008-08-16" not in text
    assert "246.31" in text  # close preserved, low widened


def test_dry_run_does_not_write(tmp_path, repair):
    path = write_csv(
        tmp_path / "VN30.csv", ["2008-08-16,900.26,900.26,900.26,900.26,1000,VN30,VN30"]
    )
    before = path.read_text(encoding="utf-8-sig")
    result = repair.repair_file(str(path), dry_run=True)

    assert result["changed"] is True
    assert path.read_text(encoding="utf-8-sig") == before


def test_clean_file_is_left_alone(tmp_path, repair):
    path = write_csv(
        tmp_path / "VN100.csv", ["2026-11-09,1767.67,1770.0,1750.0,1750.3,1000,VN100,VN100"]
    )
    before = path.read_text(encoding="utf-8-sig")
    result = repair.repair_file(str(path))

    assert result["changed"] is False
    assert path.read_text(encoding="utf-8-sig") == before


# ── freshness ─────────────────────────────────────────────────────
def test_business_days_between_counts_weekdays_only(freshness):
    # Friday -> Monday is one business day
    assert freshness.business_days_between(date(2026, 11, 6), date(2026, 11, 9)) == 1
    # a full week
    assert freshness.business_days_between(date(2026, 11, 2), date(2026, 11, 9)) == 5
    assert freshness.business_days_between(date(2026, 11, 9), date(2026, 11, 9)) == 0


def test_tet_week_stays_below_the_hard_threshold(freshness):
    # 2026-02-13 -> 2026-02-23 was the Tết closure in the stored data
    missed = freshness.business_days_between(date(2026, 2, 13), date(2026, 2, 23))
    assert missed < 8  # warn, not fail


def test_latest_session_reads_the_newest_csv(tmp_path, freshness):
    write_csv(
        tmp_path / "VNINDEX.csv",
        ["2026-11-06,1,1,1,1,1,VNINDEX,VN-Index", "2026-11-09,1,1,1,1,1,VNINDEX,VN-Index"],
    )
    write_csv(tmp_path / "VN30.csv", ["2026-10-01,1,1,1,1,1,VN30,VN30"])
    write_csv(
        tmp_path / "all_close.csv",
        ["2026-12-31,1,1"],
        header="time,VNINDEX,VN30",
    )
    assert freshness.latest_session(str(tmp_path)) == date(2026, 11, 9)


def test_staleness_thresholds(capsys):
    import importlib.util
    import pathlib
    import sys as _sys

    src = pathlib.Path(__file__).resolve().parents[1] / "src"
    spec = importlib.util.spec_from_file_location("freshness_mod", src / "check_freshness.py")
    module = importlib.util.module_from_spec(spec)
    _sys.modules["freshness_mod"] = module
    spec.loader.exec_module(module)

    # the guard must treat the ten-day outage as an outage, not a holiday
    assert module.business_days_between(date(2026, 11, 9), date(2026, 11, 23)) > 8
