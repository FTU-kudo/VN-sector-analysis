# tests/test_data_quality.py
"""
test_data_quality.py — the bar validators that keep bad rows out of the CSVs.

The numeric examples come from the real defects found in the committed data:
a phantom Saturday bar in VNINDEX on 2008-08-16 and several 2005 bars whose
close sat below their own low.
"""

from __future__ import annotations

from datetime import date, datetime, time

import pytest


def bar(day, o, h, l, c, v=1000):
    return {"date": day, "open": o, "high": h, "low": l, "close": c, "volume": v}


def dt(day, hour=18, minute=0):
    return datetime.combine(day, time(hour, minute))


# ── calendar rules ─────────────────────────────────────────────────
def test_weekend_bar_is_dropped(quality):
    rows, issues = quality.sanitize_bars(
        [bar(date(2008, 8, 16), 900.26, 900.26, 900.26, 900.26)],
        today=date(2026, 11, 23),
        now=dt(date(2026, 11, 23)),
    )
    assert rows == []
    assert [i["code"] for i in issues] == ["weekend", "empty"]


def test_future_bar_is_dropped(quality):
    rows, issues = quality.sanitize_bars(
        [bar(date(2026, 11, 24), 1, 1, 1, 1)],
        today=date(2026, 11, 23),
        now=dt(date(2026, 11, 23)),
    )
    assert rows == []
    assert issues[0]["code"] == "future"


@pytest.mark.parametrize("hour,minute,kept", [(14, 30, False), (15, 14, False), (15, 15, True)])
def test_today_is_dropped_until_the_session_closes(quality, hour, minute, kept):
    today = date(2026, 11, 23)
    rows, issues = quality.sanitize_bars(
        [bar(today, 10, 11, 9, 10.5)], today=today, now=dt(today, hour, minute)
    )
    assert bool(rows) is kept
    if not kept:
        assert "partial_session" in [i["code"] for i in issues]


# ── OHLC consistency ───────────────────────────────────────────────
def test_close_below_low_is_repaired_not_dropped(quality):
    # 2005-07-25 as stored: o 253.58 h 254.15 l 253.58 c 246.31
    rows, issues = quality.sanitize_bars(
        [bar(date(2005, 7, 25), 253.58, 254.15, 253.58, 246.31)],
        today=date(2026, 11, 23),
        now=dt(date(2026, 11, 23)),
    )
    assert len(rows) == 1
    assert rows[0]["low"] == pytest.approx(246.31)
    assert rows[0]["high"] == pytest.approx(254.15)
    assert rows[0]["close"] == pytest.approx(246.31)
    assert "ohlc_repaired" in [i["code"] for i in issues]


def test_close_above_high_is_repaired(quality):
    rows, _ = quality.sanitize_bars(
        [bar(date(2020, 6, 1), 10, 10.5, 9.5, 11.2)],
        today=date(2026, 11, 23),
        now=dt(date(2026, 11, 23)),
    )
    assert rows[0]["high"] == pytest.approx(11.2)


def test_inverted_high_low_is_repaired(quality):
    rows, issues = quality.sanitize_bars(
        [bar(date(2020, 6, 1), 10, 9.0, 10.5, 10.2)],
        today=date(2026, 11, 23),
        now=dt(date(2026, 11, 23)),
    )
    assert rows[0]["high"] >= rows[0]["low"]
    assert rows[0]["high"] >= max(rows[0]["open"], rows[0]["close"])


def test_stale_open_is_clipped_not_spread_into_the_range(quality):
    # VNFIN 2018-08-15 as stored: open carried over from the previous session
    rows, issues = quality.sanitize_bars(
        [bar(date(2018, 8, 15), 839.63, 837.05, 811.58, 811.58)],
        today=date(2026, 11, 23),
        now=dt(date(2026, 11, 23)),
    )
    assert len(rows) == 1
    assert rows[0]["open"] == pytest.approx(837.05)  # pulled into the session range
    assert rows[0]["high"] == pytest.approx(837.05)  # the real high is untouched
    assert rows[0]["low"] == pytest.approx(811.58)
    assert rows[0]["close"] == pytest.approx(811.58)
    assert [i["code"] for i in issues] == ["open_clipped"]


def test_low_open_is_clipped_upwards(quality):
    rows, issues = quality.sanitize_bars(
        [bar(date(2019, 6, 24), 800.0, 873.33, 854.21, 868.94)],
        today=date(2026, 11, 23),
        now=dt(date(2026, 11, 23)),
    )
    assert rows[0]["open"] == pytest.approx(854.21)
    assert rows[0]["low"] == pytest.approx(854.21)
    assert "open_clipped" in [i["code"] for i in issues]


def test_repair_can_be_disabled(quality):
    rows, issues = quality.sanitize_bars(
        [bar(date(2020, 6, 1), 10, 10.5, 9.5, 11.2)],
        today=date(2026, 11, 23),
        now=dt(date(2026, 11, 23)),
        repair_ohlc=False,
    )
    assert rows[0]["high"] == pytest.approx(10.5)
    assert "ohlc_skipped" in [i["code"] for i in issues]


# ── value rules ────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "payload",
    [
        bar(date(2020, 6, 1), 0, 10, 9, 9.5),
        bar(date(2020, 6, 1), -1, 10, 9, 9.5),
        {"date": date(2020, 6, 1), "open": "n/a", "high": 10, "low": 9, "close": 9.5},
        {"date": date(2020, 6, 1), "open": float("nan"), "high": 10, "low": 9, "close": 9.5},
    ],
)
def test_bad_values_are_dropped(quality, payload):
    rows, issues = quality.sanitize_bars(
        [payload], today=date(2026, 11, 23), now=dt(date(2026, 11, 23))
    )
    assert rows == []
    assert "bad_values" in [i["code"] for i in issues]


def test_duplicate_date_keeps_newest_copy(quality):
    rows, issues = quality.sanitize_bars(
        [
            bar(date(2020, 6, 1), 10, 11, 9, 10.5),
            bar(date(2020, 6, 1), 10, 12, 9, 11.5),
        ],
        today=date(2026, 11, 23),
        now=dt(date(2026, 11, 23)),
    )
    assert len(rows) == 1
    assert rows[0]["close"] == pytest.approx(11.5)
    assert "duplicate" in [i["code"] for i in issues]


def test_output_is_sorted(quality):
    rows, _ = quality.sanitize_bars(
        [
            bar(date(2020, 6, 2), 10, 11, 9, 10.5),
            bar(date(2020, 6, 1), 10, 11, 9, 10.5),
        ],
        today=date(2026, 11, 23),
        now=dt(date(2026, 11, 23)),
    )
    assert [r["date"] for r in rows] == [date(2020, 6, 1), date(2020, 6, 2)]


def test_string_dates_are_accepted(quality):
    rows, _ = quality.sanitize_bars(
        [{"date": "2020-06-01", "open": 10, "high": 11, "low": 9, "close": 10.5}],
        today=date(2026, 11, 23),
        now=dt(date(2026, 11, 23)),
    )
    assert rows[0]["date"] == date(2020, 6, 1)


# ── frames ─────────────────────────────────────────────────────────
def test_bars_to_frame_matches_the_csv_schema(quality):
    rows = [bar(date(2020, 6, 1), 10, 11, 9, 10.5, 1000)]
    frame = quality.bars_to_frame(rows, "VNINDEX", "VN-Index")
    assert list(frame.columns) == [
        "time", "open", "high", "low", "close", "volume", "symbol", "name",
    ]
    assert frame["symbol"].iloc[0] == "VNINDEX"
    assert frame["time"].iloc[0].date() == date(2020, 6, 1)


def test_merge_prefers_the_fresh_bar(quality):
    old = quality.bars_to_frame(
        [bar(date(2020, 6, 1), 10, 11, 9, 10.5), bar(date(2020, 6, 2), 10, 11, 9, 10.6)],
        "X",
        "X",
    )
    new = quality.bars_to_frame([bar(date(2020, 6, 2), 10, 11, 9, 99.0)], "X", "X")
    merged = quality.merge_frames(old, new)
    assert len(merged) == 2
    assert merged["close"].iloc[-1] == pytest.approx(99.0)


def test_merge_handles_missing_history(quality):
    new = quality.bars_to_frame([bar(date(2020, 6, 1), 10, 11, 9, 10.5)], "X", "X")
    assert len(quality.merge_frames(None, new)) == 1
    assert len(quality.merge_frames(new, None)) == 1


def test_summarize_caps_samples(quality):
    issues = [{"code": "weekend", "date": "2020-01-01", "detail": "x"}] * 100
    summary = quality.summarize_issues(issues)
    assert summary["counts"]["weekend"] == 100
    assert len(summary["samples"]["weekend"]) == quality.MAX_SAMPLES_PER_CODE
