# src/main.py
"""
main.py — Entry point pipeline VN Sector Indices Bot
Chạy: python src/main.py

Data comes from the licensed market-data API (yuanta_client.py); vnstock is no
longer used. A failure anywhere in the pipeline is reported to Telegram instead
of dying silently in the Actions log.
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import pathlib
import sys

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
    args = parser.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)-11s %(message)s"
    )

    try:
        print("\n🚀 VN Sector Indices Bot — bắt đầu pipeline\n")

        # Bước 1: Lấy dữ liệu
        print("📥 Bước 1: Lấy dữ liệu...")
        frames = m01.fetch_all(symbols=symbols or None, force_full=args.force_full)
        status = dict(getattr(m01, "LAST_RUN", {}))
        if not frames:
            raise RuntimeError("Không lấy được dữ liệu cho bất kỳ chỉ số nào")

        # Bước 2: Tính chỉ báo
        print("\n📐 Bước 2: Tính chỉ báo kỹ thuật...")
        signals = m02.run_all(frames)
        if not signals:
            raise RuntimeError("Không tạo được tín hiệu nào từ dữ liệu đã tải")

        # Bước 3: Phân tích Gemini
        print("\n🤖 Bước 3: Phân tích bằng Gemini AI...")
        analysis = m03.analyze(signals)
        print(f"  → {analysis[:100]}...")

        # Bước 4: Gửi Telegram
        print("\n📨 Bước 4: Gửi Telegram...")
        notice = _stale_notice(status)
        if notice:
            print(f"  ⚠️  {notice}")
        message = m04.format_message(signals, analysis, notice=notice)
        success = m04.send_telegram(message)

        print("\n✅ Pipeline hoàn thành!" if success else "\n⚠️  Pipeline xong nhưng Telegram thất bại.")
        return 0 if success else 1

    except Exception as exc:  # noqa: BLE001 - alert, then fail loudly
        log.exception("Pipeline lỗi: %s", exc)
        m04.send_plain(
            "🚨 VN Sector Bot thất bại\n"
            f"{type(exc).__name__}: {exc}\n"
            "Xem log: GitHub → Actions → VN Sector Indices Bot"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
