"""
02_indicators.py — Tính chỉ báo kỹ thuật cho từng chỉ số
"""

import numpy as np
import pandas as pd


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).round(2)


def calc_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Nhận DataFrame OHLCV, trả về DataFrame có thêm các cột chỉ báo."""
    df = df.copy().sort_values("time").reset_index(drop=True)
    c  = df["close"]

    # ── Moving Averages ──────────────────────────────────────────
    df["ma20"]  = c.rolling(20).mean().round(2)
    df["ma50"]  = c.rolling(50).mean().round(2)
    df["ma200"] = c.rolling(200).mean().round(2)

    # ── Bollinger Bands (20, 2σ) ─────────────────────────────────
    df["bb_mid"]   = df["ma20"]
    df["bb_std"]   = c.rolling(20).std()
    df["bb_upper"] = (df["bb_mid"] + 2 * df["bb_std"]).round(2)
    df["bb_lower"] = (df["bb_mid"] - 2 * df["bb_std"]).round(2)
    df["%b"]       = ((c - df["bb_lower"]) /
                      (df["bb_upper"] - df["bb_lower"])).round(4)
    df.drop(columns=["bb_std"], inplace=True)

    # ── RSI (14) ─────────────────────────────────────────────────
    df["rsi"] = calc_rsi(c, 14)

    # ── MACD (12/26/9) ───────────────────────────────────────────
    ema12             = c.ewm(span=12, adjust=False).mean()
    ema26             = c.ewm(span=26, adjust=False).mean()
    df["macd"]        = (ema12 - ema26).round(2)
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean().round(2)
    df["macd_hist"]   = (df["macd"] - df["macd_signal"]).round(2)

    return df


def build_signal(df: pd.DataFrame) -> dict:
    """
    Tạo dict tín hiệu kỹ thuật từ 2 phiên cuối.
    Dùng để truyền cho Gemini AI.
    """
    last  = df.iloc[-1]
    prev  = df.iloc[-2]
    first = df.iloc[0]

    close  = last["close"]
    chg_1d = (close - prev["close"]) / prev["close"] * 100

    # Tìm giá ~1 năm trước
    one_year_ago = last["time"] - pd.DateOffset(years=1)
    df_past = df[df["time"] <= one_year_ago]
    chg_1y  = ((close - df_past["close"].iloc[-1]) /
                df_past["close"].iloc[-1] * 100) if len(df_past) else None

    # MA trend
    ma_trend = "Tăng (Bullish)" if last["ma50"] > last["ma200"] else "Giảm (Bearish)"

    # MACD cross (hôm nay vs hôm qua)
    if last["macd"] > last["macd_signal"] and prev["macd"] <= prev["macd_signal"]:
        macd_status = "Golden cross (Bullish)"
    elif last["macd"] < last["macd_signal"] and prev["macd"] >= prev["macd_signal"]:
        macd_status = "Death cross (Bearish)"
    elif last["macd"] > last["macd_signal"]:
        macd_status = "MACD trên Signal (Bullish)"
    else:
        macd_status = "MACD dưới Signal (Bearish)"

    # RSI
    rsi = last["rsi"]
    if rsi > 70:
        rsi_status = f"Quá mua ({rsi:.1f})"
    elif rsi < 30:
        rsi_status = f"Quá bán ({rsi:.1f})"
    else:
        rsi_status = f"Trung tính ({rsi:.1f})"

    # Bollinger
    if close > last["bb_upper"]:
        bb_status = "Giá vượt dải BB trên — có thể quá mua"
    elif close < last["bb_lower"]:
        bb_status = "Giá phá dải BB dưới — có thể quá bán"
    else:
        bb_status = f"Trong dải Bollinger (%B={last['%b']:.2f})"

    return {
        "symbol":      last["symbol"],
        "name":        last["name"],
        "date":        str(last["time"].date()),
        "close":       round(close, 2),
        "change_1d":   round(chg_1d, 2),
        "change_1y":   round(chg_1y, 2) if chg_1y is not None else None,
        "ma_trend":    ma_trend,
        "ma50":        round(last["ma50"],  2),
        "ma200":       round(last["ma200"], 2),
        "rsi":         rsi_status,
        "macd":        macd_status,
        "bollinger":   bb_status,
    }


def run_all(frames: dict) -> list[dict]:
    """Tính chỉ báo cho tất cả chỉ số, trả về list signal dict."""
    signals = []
    for symbol, df in frames.items():
        df_ind = calc_indicators(df)
        sig    = build_signal(df_ind)
        signals.append(sig)
        print(f"  ✅ {sig['name']:25s} ({symbol})  "
              f"close={sig['close']:,.2f}  RSI={sig['rsi']}")
    return signals


if __name__ == "__main__":
    # Test nhanh với 1 file CSV
    import os, sys
    DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
    csv = os.path.join(DATA_DIR, "VNMID.csv")
    if os.path.exists(csv):
        df = pd.read_csv(csv, parse_dates=["time"])
        df_ind = calc_indicators(df)
        sig    = build_signal(df_ind)
        print(sig)
    else:
        print("Chưa có data — chạy 01_fetch.py trước")
