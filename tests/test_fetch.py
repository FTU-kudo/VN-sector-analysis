# tests/test_fetch.py
"""
test_fetch.py — cache behaviour of 01_fetch.py: incremental merges, the
no-regression guard, failure handling, self-healing of old caches and the
quality report. No network access: the client is faked.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time
from pathlib import Path

import pytest


def bar(day, close, o=None, h=None, l=None, v=1000):
    o = close if o is None else o
    h = close + 1 if h is None else h
    l = close - 1 if l is None else l
    return {"date": day, "open": o, "high": h, "low": l, "close": close, "volume": v}


class FakeClient:
    """Returns canned bars per symbol and fails on demand."""

    def __init__(self, bars_by_symbol=None, error=None, board_error=None):
        self.bars_by_symbol = bars_by_symbol or {}
        self.error = error
        self.board_error = board_error
        self.calls = []
        self.stats = {"requests": 0, "challenges": 0, "retries": 0}

    def history(self, symbol, start):
        self.calls.append((symbol, start))
        if self.error:
            raise self.error
        return list(self.bars_by_symbol.get(symbol, []))

    def index_board(self):
        if self.board_error:
            raise self.board_error
        return []


@pytest.fixture
def sandbox(fetch_mod, tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_mod, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(fetch_mod, "QUALITY_PATH", str(tmp_path / "quality_report.json"))
    monkeypatch.setattr(fetch_mod, "REPAIR_OHLC", True)
    return tmp_path


def read_csv(path: Path):
    import pandas as pd

    return pd.read_csv(path, parse_dates=["time"], encoding="utf-8-sig")


# ── single symbol ──────────────────────────────────────────────────
def test_fresh_fetch_writes_the_csv(sandbox, fetch_mod):
    client = FakeClient({"VNINDEX": [bar(date(2020, 6, 1), 100.0), bar(date(2020, 6, 2), 101.0)]})
    frame, meta = fetch_mod.fetch_one("VNINDEX", "VN-Index", client)

    assert meta["status"] == "ok"
    assert meta["new_bars"] == 2
    assert meta["latest"] == "2020-06-02"
    assert len(frame) == 2
    stored = read_csv(sandbox / "VNINDEX.csv")
    assert list(stored["symbol"]) == ["VNINDEX", "VNINDEX"]
    assert stored["name"].iloc[0] == "VN-Index"
    # no cache existed -> full history requested
    assert client.calls[0][1] == fetch_mod.HISTORY_START


def test_second_run_only_requests_the_overlap(sandbox, fetch_mod):
    first = FakeClient({"VN30": [bar(date(2020, 6, 1), 100.0), bar(date(2020, 6, 2), 101.0)]})
    fetch_mod.fetch_one("VN30", "VN30", first)

    second = FakeClient({"VN30": [bar(date(2020, 6, 2), 101.5), bar(date(2020, 6, 3), 102.0)]})
    frame, meta = fetch_mod.fetch_one("VN30", "VN30", second)

    requested_from = second.calls[0][1]
    assert requested_from < date(2020, 6, 2)  # overlap window, not full history
    assert meta["new_bars"] == 1
    assert len(frame) == 3
    assert frame["close"].iloc[1] == pytest.approx(101.5)  # overlap refreshed


def test_lagging_source_keeps_cache_and_is_reported(sandbox, fetch_mod):
    fetch_mod.fetch_one(
        "VNINDEX", "VN-Index", FakeClient({"VNINDEX": [bar(date(2020, 6, 5), 105.0)]})
    )

    lagging = FakeClient({"VNINDEX": [bar(date(2020, 6, 1), 100.0)]})
    frame, meta = fetch_mod.fetch_one("VNINDEX", "VN-Index", lagging)

    # history is merged, never truncated, and the lagging feed is reported
    assert meta["status"] == "behind"
    assert meta["source_latest"] == "2020-06-01"
    assert frame["time"].max().date() == date(2020, 6, 5)
    stored = read_csv(sandbox / "VNINDEX.csv")
    assert stored["time"].max().date() == date(2020, 6, 5)
    assert date(2020, 6, 1) in [d.date() for d in stored["time"]]


def test_failed_fetch_keeps_the_cache(sandbox, fetch_mod, yuanta):
    fetch_mod.fetch_one(
        "VNINDEX", "VN-Index", FakeClient({"VNINDEX": [bar(date(2020, 6, 5), 105.0)]})
    )
    failing = FakeClient(error=yuanta.YuantaError("boom"))
    frame, meta = fetch_mod.fetch_one("VNINDEX", "VN-Index", failing)

    assert meta["status"] == "failed"
    assert "boom" in meta["error"]
    assert len(frame) == 1
    assert read_csv(sandbox / "VNINDEX.csv")["close"].iloc[-1] == pytest.approx(105.0)


def test_failed_fetch_without_cache_returns_nothing(sandbox, fetch_mod, yuanta):
    frame, meta = fetch_mod.fetch_one(
        "VNINDEX", "VN-Index", FakeClient(error=yuanta.YuantaError("down"))
    )
    assert frame is None
    assert meta["status"] == "failed"
    assert not (sandbox / "VNINDEX.csv").exists()


def test_empty_response_marks_the_symbol_empty(sandbox, fetch_mod):
    frame, meta = fetch_mod.fetch_one("VNUTI", "Tiện ích", FakeClient({}))
    assert frame is None
    assert meta["status"] == "empty"


def test_legacy_cache_is_cleaned_on_load(sandbox, fetch_mod):
    """The old pipeline stored a Saturday bar and a close below the low."""
    legacy = (
        "time,open,high,low,close,volume,symbol,name\n"
        "2008-08-15,488.94,490.0,486.0,488.94,1000,VNINDEX,VN-Index\n"
        "2008-08-16,900.26,900.26,900.26,900.26,1000,VNINDEX,VN-Index\n"
        "2008-08-19,511.53,514.0,509.0,511.53,1000,VNINDEX,VN-Index\n"
    )
    (sandbox / "VNINDEX.csv").write_text(legacy, encoding="utf-8-sig")

    client = FakeClient({"VNINDEX": [bar(date(2008, 8, 20), 508.47)]})
    frame, meta = fetch_mod.fetch_one("VNINDEX", "VN-Index", client)

    dates = [d.date() for d in frame["time"]]
    assert date(2008, 8, 16) not in dates
    assert meta["status"] == "ok"
    stored = read_csv(sandbox / "VNINDEX.csv")
    assert date(2008, 8, 16) not in [d.date() for d in stored["time"]]


def test_partial_session_bar_is_not_stored(sandbox, fetch_mod):
    today = datetime.now(fetch_mod.yc.VN_TZ).date()
    mid_session = datetime.combine(today, time(10, 0), tzinfo=fetch_mod.yc.VN_TZ)
    client = FakeClient({"VNINDEX": [bar(date(2020, 6, 1), 100.0), bar(today, 111.0)]})
    frame, _ = fetch_mod.fetch_one("VNINDEX", "VN-Index", client, now=mid_session)

    stored = read_csv(sandbox / "VNINDEX.csv")
    assert today not in [d.date() for d in stored["time"]]
    assert len(frame) == 1


def test_unchanged_data_does_not_rewrite_the_file(sandbox, fetch_mod):
    bars = [bar(date(2020, 6, 1), 100.0), bar(date(2020, 6, 2), 101.0)]
    path = sandbox / "VNINDEX.csv"
    fetch_mod.fetch_one("VNINDEX", "VN-Index", FakeClient({"VNINDEX": bars}))
    first_mtime = path.stat().st_mtime_ns

    fetch_mod.fetch_one("VNINDEX", "VN-Index", FakeClient({"VNINDEX": bars}))
    assert path.stat().st_mtime_ns == first_mtime


# ── whole run ─────────────────────────────────────────────────────
def test_fetch_all_writes_pivot_and_quality_report(sandbox, fetch_mod, monkeypatch, yuanta):
    bars = {
        "VNINDEX": [bar(date(2020, 6, 1), 100.0), bar(date(2020, 6, 2), 101.0)],
        "VN30": [bar(date(2020, 6, 1), 50.0), bar(date(2020, 6, 2), 51.0)],
    }
    fake = FakeClient(bars, board_error=yuanta.YuantaError("board unavailable"))
    monkeypatch.setattr(fetch_mod.yc, "YuantaClient", lambda *a, **k: fake)
    monkeypatch.setattr(fetch_mod, "INDICES", {"VNINDEX": "VN-Index", "VN30": "VN30"})
    frames = fetch_mod.fetch_all()

    assert set(frames) == {"VNINDEX", "VN30"}
    pivot = read_csv(sandbox / "all_close.csv")
    assert list(pivot.columns) == ["time", "VNINDEX", "VN30"]
    assert len(pivot) == 2

    report = json.loads((sandbox / "quality_report.json").read_text())
    assert report["latest_session"] == "2020-06-02"
    assert report["symbols"]["VNINDEX"]["status"] == "ok"
    assert report["board_check"]["available"] is False
    assert fetch_mod.LAST_RUN["symbols_ok"] == 2
    assert fetch_mod.LAST_RUN["latest_session"] == "2020-06-02"


def test_fetch_all_records_staleness(sandbox, fetch_mod, monkeypatch):
    fake = FakeClient({"VNINDEX": [bar(date(2020, 6, 1), 100.0)]})
    monkeypatch.setattr(fetch_mod.yc, "YuantaClient", lambda *a, **k: fake)
    monkeypatch.setattr(fetch_mod, "INDICES", {"VNINDEX": "VN-Index"})
    fetch_mod.fetch_all()

    assert fetch_mod.LAST_RUN["stale_days"] > fetch_mod.STALE_WARN_DAYS
    report = json.loads((sandbox / "quality_report.json").read_text())
    assert report["stale_days"] == fetch_mod.LAST_RUN["stale_days"]


def test_dead_source_stops_calling_after_three_failures(
    sandbox, fetch_mod, monkeypatch, yuanta
):
    """Nguồn chết hẳn: không bắt 18 chỉ số chờ retry, phần còn lại dùng cache."""
    symbols = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    for symbol in symbols:
        (sandbox / f"{symbol}.csv").write_text(
            "time,open,high,low,close,volume,symbol,name\n"
            f"2026-11-09,10,11,9,10,1000,{symbol},{symbol}\n",
            encoding="utf-8-sig",
        )

    fake = FakeClient(error=yuanta.YuantaError("host down"))
    monkeypatch.setattr(fetch_mod.yc, "YuantaClient", lambda *a, **k: fake)
    monkeypatch.setattr(fetch_mod, "INDICES", {s: s for s in symbols})

    frames = fetch_mod.fetch_all()

    assert len(fake.calls) == fetch_mod.MAX_CONSECUTIVE_FAILURES  # dừng gọi API
    assert set(frames) == set(symbols)  # cache vẫn được dùng
    report = json.loads((sandbox / "quality_report.json").read_text())
    assert report["symbols"]["DDD"]["status"] == "skipped"
    assert report["symbols"]["EEE"]["status"] == "skipped"
    assert fetch_mod.LAST_RUN["skipped"] == ["DDD", "EEE"]
