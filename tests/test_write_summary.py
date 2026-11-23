# tests/test_write_summary.py
"""
test_write_summary.py — bảng tóm tắt trong tab Actions.

Mục tiêu: mở một lần chạy là biết ngay phiên dữ liệu nào, chỉ số nào lỗi, dữ
liệu bị sửa gì và tin nhắn Telegram đã đi chưa — không phải đọc log từng bước.
"""

from __future__ import annotations

import json
import sys

REPORT = {
    "latest_session": "2026-11-09",
    "stale_days": 14,
    "issue_count": 3,
    "source_host": "https://ysradar.example",
    "issue_counts": {"VNINDEX": {"weekend": 1}},
    "symbols": {
        "VNINDEX": {
            "status": "ok",
            "rows": 5685,
            "latest": "2026-11-09",
            "issues": {"counts": {"weekend": 1, "open_clipped": 2}},
        },
        "VNUTI": {"status": "failed", "rows": 0, "latest": None, "issues": {"counts": {}}},
    },
    "board_check": {"available": False, "error": "board blocked"},
    "request_stats": {"requests": 19, "challenges": 1, "retries": 0},
}

STATUS = {
    "mode": "report",
    "generated_at": "2026-11-23T18:00:00+07:00",
    "symbols_ok": 17,
    "symbols_total": 18,
    "failed": ["VNUTI"],
    "signals": 17,
    "analysis_ok": True,
    "telegram_sent": True,
    "message_chars": 2500,
    "telegram_error": "",
}

TELEGRAM = {
    "token_ok": True,
    "chat_ok": True,
    "chat_title": "VN Market",
    "chat_type": "channel",
    "send_ok": None,
}


def test_summary_reports_the_essentials(write_summary):
    text = write_summary.build_summary(REPORT, STATUS, TELEGRAM)

    assert "2026-11-09" in text and "cũ 14 ngày" in text
    assert "17/18" in text and "nguồn lỗi: VNUTI" in text
    assert "đã gửi" in text and "2500 ký tự" in text
    assert "VN Market" in text
    assert "| VNINDEX | ok | 5685 | 2026-11-09 | open_clipped×2, weekend×1 |" in text
    assert "board blocked" in text
    assert "requests=19" in text


def test_summary_survives_missing_artifacts(write_summary):
    text = write_summary.build_summary(None, None, None)

    assert text.startswith("## VN Sector Bot")
    assert "—" in text


def test_summary_lists_skipped_symbols(write_summary):
    status = dict(STATUS, skipped=["VNUTI"])
    text = write_summary.build_summary(REPORT, status, TELEGRAM)

    assert "bỏ qua: VNUTI" in text


def test_summary_marks_dry_run(write_summary):
    status = dict(STATUS, mode="dry-run", telegram_sent=None, analysis_ok=None)
    text = write_summary.build_summary(REPORT, status, None)

    assert "dry-run" in text
    assert "chưa gửi" in text
    assert "bỏ qua (dry-run)" in text


def test_summary_shows_telegram_failure_reason(write_summary):
    status = dict(STATUS, telegram_sent=False, telegram_error="HTTP 400: chat not found")
    text = write_summary.build_summary(REPORT, status, None)

    assert "thất bại" in text
    assert "chat not found" in text


def test_summary_shows_broken_telegram_config(write_summary):
    broken = {"token_ok": False, "chat_ok": False, "send_ok": None, "token_error": "Unauthorized"}
    text = write_summary.build_summary(REPORT, STATUS, broken)

    assert "lỗi ❌" in text and "Unauthorized" in text


def test_main_writes_to_the_step_summary_file(write_summary, monkeypatch, tmp_path):
    for name, payload in (
        ("quality_report.json", REPORT),
        ("run_status.json", STATUS),
        ("telegram_check.json", TELEGRAM),
    ):
        (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")

    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(
        sys, "argv", ["write_summary.py", "--data-dir", str(tmp_path)]
    )

    assert write_summary.main() == 0
    written = summary.read_text(encoding="utf-8")
    assert "VN Sector Bot" in written
    assert "VNINDEX" in written
