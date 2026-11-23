# src/write_summary.py
"""
write_summary.py — Biến kết quả một lần chạy thành bảng Markdown trong tab Actions.

Đọc ba file do pipeline tạo ra và ghi vào $GITHUB_STEP_SUMMARY, để không phải
mở log từng bước mới biết: phiên mới nhất là ngày nào, chỉ số nào lỗi, dữ liệu
đã được sửa gì, và tin nhắn Telegram đã gửi được chưa.

Không bao giờ làm hỏng run: thiếu file thì ghi chú, exit code luôn là 0.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
QUALITY = "quality_report.json"
STATUS = "run_status.json"
TELEGRAM = "telegram_check.json"


def load(name: str, data_dir: str = DATA_DIR) -> Optional[Dict[str, Any]]:
    path = os.path.join(data_dir, name)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _session(latest: Optional[str], stale: Optional[int]) -> str:
    if not latest:
        return "—"
    if isinstance(stale, int):
        return f"{latest} (cũ {stale} ngày)"
    return latest


def _issues_text(counts: Dict[str, int]) -> str:
    return ", ".join(f"{code}×{n}" for code, n in sorted(counts.items())) if counts else "—"


def _telegram_report_text(status: Optional[Dict[str, Any]]) -> str:
    if not status or status.get("telegram_sent") is None:
        return "— (chưa gửi, chế độ dry-run)"
    if status.get("telegram_sent"):
        return f"đã gửi ✅ ({status.get('message_chars', 0)} ký tự)"
    error = (status.get("telegram_error") or "").strip()
    return f"thất bại ❌{(' — ' + error) if error else ''}"


def _telegram_check_text(check: Optional[Dict[str, Any]]) -> str:
    if not check:
        return "— (chưa chạy)"
    if check.get("token_ok") and check.get("chat_ok") and check.get("send_ok") is not False:
        chat = check.get("chat_title") or check.get("chat_id")
        return f"token + chat OK ✅ ({chat})"
    reason = check.get("token_error") or check.get("chat_error") or check.get("send_error")
    return f"lỗi ❌ — {reason}"


def build_summary(
    report: Optional[Dict[str, Any]],
    status: Optional[Dict[str, Any]],
    telegram: Optional[Dict[str, Any]],
) -> str:
    report = report or {}
    status = status or {}

    symbols_ok = status.get("symbols_ok")
    symbols_total = status.get("symbols_total")
    failed = status.get("failed") or []
    skipped = status.get("skipped") or []
    symbols_text = (
        f"{symbols_ok}/{symbols_total}" if symbols_ok is not None and symbols_total else "—"
    )
    if failed:
        symbols_text += f" — nguồn lỗi: {', '.join(failed)}"
    if skipped:
        symbols_text += f" — bỏ qua: {', '.join(skipped)}"

    analysis = "bỏ qua (dry-run)" if status.get("analysis_ok") is None else (
        "OK ✅" if status.get("analysis_ok") else "lỗi ❌"
    )

    rows: List[tuple] = [
        ("Chế độ", status.get("mode", "—")),
        ("Thời điểm", status.get("generated_at", "—")),
        ("Phiên mới nhất", _session(report.get("latest_session") or status.get("latest_session"),
                                    report.get("stale_days", status.get("stale_days")))),
        ("Chỉ số", symbols_text),
        ("Tín hiệu", str(status.get("signals", "—"))),
        ("Vấn đề dữ liệu đã xử lý", str(report.get("issue_count", 0))),
        ("Phân tích AI", analysis),
        ("Telegram — báo cáo", _telegram_report_text(status)),
        ("Telegram — cấu hình", _telegram_check_text(telegram)),
    ]
    if report.get("source_host"):
        rows.append(("Nguồn dữ liệu", report["source_host"]))
    if report.get("request_stats"):
        stats = report["request_stats"]
        rows.append(("HTTP", ", ".join(f"{k}={v}" for k, v in sorted(stats.items()))))

    body = "\n".join(f"| {key} | {value} |" for key, value in rows)
    out = [f"## VN Sector Bot — kết quả lần chạy\n| Mục | Giá trị |\n|---|---|\n{body}\n"]

    symbols = report.get("symbols") or {}
    if symbols:
        lines = ["### Dữ liệu theo chỉ số", "| Mã | Trạng thái | Số nến | Phiên cuối | Đã sửa |", "|---|---|---|---|---|"]
        for symbol, meta in symbols.items():
            counts = (meta.get("issues") or {}).get("counts") or {}
            lines.append(
                f"| {symbol} | {meta.get('status', '—')} | {meta.get('rows', 0)} | "
                f"{meta.get('latest') or '—'} | {_issues_text(counts)} |"
            )
        out.append("\n".join(lines) + "\n")

    board = report.get("board_check") or {}
    if board.get("available") is False and board.get("error"):
        out.append(f"\n> Kiểm tra chéo bảng chỉ số không chạy được: {board['error']}\n")

    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ghi summary cho GitHub Actions")
    parser.add_argument("--out", default=None, help="ghi ra file thay vì $GITHUB_STEP_SUMMARY")
    parser.add_argument("--data-dir", default=DATA_DIR)
    args = parser.parse_args()

    text = build_summary(
        load(QUALITY, args.data_dir),
        load(STATUS, args.data_dir),
        load(TELEGRAM, args.data_dir),
    )

    target = args.out or os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(text)
        print(f"Đã ghi summary vào {target}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
