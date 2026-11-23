# src/main.py
"""
main.py — Entry point pipeline VN Sector Indices Bot
Chạy: python src/main.py [--dry-run] [--force-full] [--symbols VNINDEX,VN30]

Data comes from the licensed market-data API (yuanta_client.py); vnstock is no
longer used. A failure anywhere in the pipeline is reported to Telegram instead
of dying silently in the Actions log, and every run leaves data/run_status.json
so the Actions summary can show what happened.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import pathlib
import sys
from datetime import datetime

log = logging.getLogger("main")

BASE = pathlib.Path(__file__).parent


def _load(fname: str):
    """Load module từ file có prefix số (vd: 01_fetch.py)."""
    path = BASE / fname
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m01 = _load("01_fetch.py")
m02 = _load("02_indicators.py")
m03 = _load("03_analysis.py")
m04 = _load("04_telegram.py")


def _write_status(payload: dict) -> None:
    """Ghi trạng thái lần chạy để bước summary đọc được (không commit)."""
    path = os.path.join(m01.DATA_DIR, "run_status.json")
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
    except OSError as exc:
        log.warning("Không ghi được run_status.json: %s", exc)


def _stale_notice(status: dict) -> str:
    """Human-readable warning when the newest session is old or partial."""
    notes = []
    stale = status.get("stale_days")
    latest = status.get("latest_session")
    if latest and isinstance(stale, int) and stale > m01.STALE_WARN_DAYS:
        notes.append(f"Dữ liệu mới nhất là phiên {latest} (cũ {stale} ngày)")
    failed = status.get("failed") or []
    if failed:
        notes.append("Không lấy được: " + ", ".join(failed))
    return " — ".join(notes)


def main() -> int:
    parser = argparse.ArgumentParser(description="VN Sector Indices Bot")
    parser.add_argument(
        "--force-full", action="store_true", help="tải lại toàn bộ lịch sử từ nguồn"
    )
    parser.add_argument(
        "--symbols", default="", help="chỉ xử lý các mã này (phân cách bằng dấu phẩy)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="chỉ tải dữ liệu và tính chỉ báo: không gọi Gemini, không gửi Telegram",
    )
    args = parser.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)-11s %(message)s"
    )

    status: dict = {
        "generated_at": datetime.now(m01.yc.VN_TZ).isoformat(timespec="seconds"),
        "mode": "dry-run" if args.dry_run else "report",
        "telegram_sent": None,
        "analysis_ok": None,
        "symbols_ok": 0,
        "symbols_total": 0,
        "failed": [],
    }

    try:
        print("\n🚀 VN Sector Indices Bot — bắt đầu pipeline\n")

        # Bước 1: Lấy dữ liệu
        print("📥 Bước 1: Lấy dữ liệu...")
        frames = m01.fetch_all(symbols=symbols or None, force_full=args.force_full)
        status.update(dict(getattr(m01, "LAST_RUN", {})))
        status["symbols_ok"] = len(frames)
        if not frames:
            raise RuntimeError("Không lấy được dữ liệu cho bất kỳ chỉ số nào")

        # Bước 2: Tính chỉ báo
        print("\n📐 Bước 2: Tính chỉ báo kỹ thuật...")
        signals = m02.run_all(frames)
        if not signals:
            raise RuntimeError("Không tạo được tín hiệu nào từ dữ liệu đã tải")
        status["signals"] = len(signals)

        if args.dry_run:
            print("\n🧪 Dry-run: không gọi Gemini, không gửi Telegram.\n")
            for sig in signals:
                print(
                    f"  {sig['symbol']:11s} {sig['date']}  {sig['close']:>10,.2f}  "
                    f"{sig['change_1d']:+.2f}%  {sig['rsi']}"
                )
            _write_status(status)
            print("\n✅ Dry-run xong.")
            return 0

        # Bước 3: Phân tích Gemini
        print("\n🤖 Bước 3: Phân tích bằng Gemini AI...")
        analysis = m03.analyze(signals)
        status["analysis_ok"] = not analysis.lstrip().startswith(("❌", "⚠️"))
        print(f"  → {analysis[:100]}...")

        # Bước 4: Gửi Telegram
        print("\n📨 Bước 4: Gửi Telegram...")
        notice = _stale_notice(status)
        if notice:
            print(f"  ⚠️  {notice}")
        message = m04.format_message(signals, analysis, notice=notice)
        status["message_chars"] = len(message)
        sent = m04.send_telegram(message)
        status["telegram_sent"] = bool(sent)
        status["telegram_error"] = "" if sent else getattr(m04, "LAST_ERROR", "")
        _write_status(status)

        print("\n✅ Pipeline hoàn thành!" if sent else "\n⚠️  Pipeline xong nhưng gửi Telegram thất bại.")
        return 0 if sent else 1

    except Exception as exc:  # noqa: BLE001 - alert, then fail loudly
        log.exception("Pipeline lỗi: %s", exc)
        status["error"] = f"{type(exc).__name__}: {exc}"
        _write_status(status)
        m04.send_plain(
            "🚨 VN Sector Bot thất bại\n"
            f"{type(exc).__name__}: {exc}\n"
            "Xem log: GitHub → Actions → VN Sector Indices Bot"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
