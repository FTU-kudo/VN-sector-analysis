"""
main.py — Entry point pipeline VN Sector Indices Bot
Chạy: python src/main.py
"""

import os, sys, importlib.util, pathlib

def _load(fname):
    """Load module từ file có prefix số (vd: 01_fetch.py)."""
    p    = pathlib.Path(__file__).parent / fname
    spec = importlib.util.spec_from_file_location(fname.stem, p)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

m01 = _load(pathlib.Path("01_fetch.py"))
m02 = _load(pathlib.Path("02_indicators.py"))
m03 = _load(pathlib.Path("03_analysis.py"))
m04 = _load(pathlib.Path("04_telegram.py"))


def main():
    print("\n🚀 VN Sector Indices Bot — bắt đầu pipeline\n")

    # Bước 1: Fetch data
    print("📥 Bước 1: Lấy dữ liệu...")
    frames = m01.fetch_all()
    if not frames:
        print("❌ Không lấy được dữ liệu. Dừng.")
        sys.exit(1)

    # Bước 2: Tính chỉ báo
    print("\n📐 Bước 2: Tính chỉ báo kỹ thuật...")
    signals = m02.run_all(frames)

    # Bước 3: Phân tích Gemini
    print("\n🤖 Bước 3: Phân tích bằng Gemini AI...")
    analysis = m03.analyze(signals)
    print(f"  → {analysis[:100]}...")

    # Bước 4: Gửi Telegram
    print("\n📨 Bước 4: Gửi Telegram...")
    message = m04.format_message(signals, analysis)
    success = m04.send_telegram(message)

    print("\n✅ Pipeline hoàn thành!" if success
          else "\n⚠️  Pipeline xong nhưng Telegram thất bại.")
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
