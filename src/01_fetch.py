"""
01_fetch.py — Lấy dữ liệu OHLCV cho 17 chỉ số VN
Chạy: python src/01_fetch.py
"""

import os
import pandas as pd
from datetime import date
from vnstock import Quote

# ── Cấu hình ────────────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)

TODAY  = date.today().strftime("%Y-%m-%d")
SOURCE = "VCI"

INDICES = {
    # Chỉ số thị trường chung
    "VNINDEX" : "VN-Index",
    "VN30" : "VN30",
    "VN100" : "VN100",
    "VNALL" : "VN All Share",
    "HNXINDEX" : "HNX-Index",
    "UPCOMINDEX" : "UPCOM-Index",

    # Vốn hóa trung – nhỏ
    "VNMID":  "VN Mid Cap",
    "VNSML":  "VN Small Cap",
    
    # Ngành
    "VNFIN":  "Tài chính",
    "VNREAL": "Bất động sản",
    "VNIT":   "Công nghệ thông tin",
    "VNHEAL": "Y tế",
    "VNENE":  "Năng lượng",
    "VNIND":  "Công nghiệp",
    "VNMAT":  "Nguyên vật liệu",
    "VNCONS": "Tiêu dùng thiết yếu",
    "VNCOND": "Tiêu dùng tùy ý",
}


def normalize(df: pd.DataFrame, symbol: str, name: str) -> pd.DataFrame:
    """Chuẩn hoá tên cột từ vnstock."""
    rename = {}
    for col in df.columns:
        c = col.lower()
        if c in ("time", "date", "tradingdate"):    rename[col] = "time"
        elif c == "open":                            rename[col] = "open"
        elif c == "high":                            rename[col] = "high"
        elif c == "low":                             rename[col] = "low"
        elif c == "close":                           rename[col] = "close"
        elif c in ("volume", "totalvolume"):         rename[col] = "volume"
    df = df.rename(columns=rename)
    df["time"]   = pd.to_datetime(df["time"])
    df["symbol"] = symbol
    df["name"]   = name
    return df.sort_values("time").reset_index(drop=True)


def fetch_one(symbol: str, name: str) -> pd.DataFrame | None:
    cache_path = os.path.join(DATA_DIR, f"{symbol}.csv")

    # ── Đọc cache nếu có ────────────────────────────────────────
    if os.path.exists(cache_path):
        df_old = pd.read_csv(cache_path, parse_dates=["time"])
        last_dt = df_old["time"].max()
        if last_dt.date() >= date.today():
            print(f"  ⚡ {name:25s} ({symbol})  cache còn mới, bỏ qua")
            return df_old

        # Chỉ fetch dữ liệu mới từ ngày cuối cache
        start = last_dt.strftime("%Y-%m-%d")
        print(f"  🔄 {name:25s} ({symbol})  cập nhật từ {start}...")
        try:
            df_new = Quote(symbol=symbol, source=SOURCE).history(
                start=start, end=TODAY, interval="1D"
            )
            df_new = normalize(df_new, symbol, name)
            df_all = (pd.concat([df_old, df_new])
                        .drop_duplicates("time")
                        .sort_values("time")
                        .reset_index(drop=True))
        except Exception as e:
            print(f"  ⚠️  Lỗi cập nhật {symbol}: {e} — dùng cache cũ")
            return df_old
    else:
        # Fetch toàn bộ lịch sử
        print(f"  ⬇️  {name:25s} ({symbol})  fetch từ đầu...")
        try:
            df_all = Quote(symbol=symbol, source=SOURCE).history(
                start="2000-01-01", end=TODAY, interval="1D"
            )
            df_all = normalize(df_all, symbol, name)
        except Exception as e:
            print(f"  ❌ Lỗi fetch {symbol}: {e}")
            return None

    # ── Lưu cache ───────────────────────────────────────────────
    df_all.to_csv(cache_path, index=False, encoding="utf-8-sig")
    n_sessions = len(df_all)
    date_range = f"{df_all['time'].min().date()} → {df_all['time'].max().date()}"
    print(f"  ✅ {name:25s} ({symbol})  {n_sessions:>4} phiên  [{date_range}]")
    return df_all


def fetch_all() -> dict[str, pd.DataFrame]:
    print("=" * 60)
    print("  FETCH: 17 chỉ số VN")
    print("=" * 60)
    results = {}
    for symbol, name in INDICES.items():
        df = fetch_one(symbol, name)
        if df is not None:
            results[symbol] = df

    # Lưu bảng pivot giá đóng cửa tổng hợp
    if results:
        df_close = (pd.concat(results.values())
                      .pivot_table(index="time", columns="symbol",
                                   values="close", aggfunc="last"))
        col_order = [s for s in INDICES if s in df_close.columns]
        df_close  = df_close[col_order]
        df_close.to_csv(os.path.join(DATA_DIR, "all_close.csv"),
                        encoding="utf-8-sig")
        print(f"\n✅ Saved data/{'{symbol}'}.csv × {len(results)} files + all_close.csv")

    return results


if __name__ == "__main__":
    fetch_all()
