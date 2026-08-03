"""
02_indicators.py — Tính toán chỉ báo kỹ thuật đầy đủ (MA, BB, RSI, MACD, ADX, Ichimoku, SMC)
và tạo tín hiệu cho từng mã hoặc danh mục.
Phiên bản tối ưu, vector hóa, xử lý an toàn dữ liệu thiếu / NaN.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Union

import numpy as np
import pandas as pd

log = logging.getLogger("indicators")


# ─────────────────────────────────────────────────────────────────────
# Các hàm tiện ích tính chỉ báo (được gọi trong groupby)
# ─────────────────────────────────────────────────────────────────────

def _add_ma(df: pd.DataFrame, close: pd.Series) -> None:
    df["ma20"] = close.rolling(20, min_periods=1).mean().round(2)
    df["ma50"] = close.rolling(50, min_periods=1).mean().round(2)
    df["ma200"] = close.rolling(200, min_periods=1).mean().round(2)


def _add_bollinger(df: pd.DataFrame, close: pd.Series) -> None:
    roll_mean = close.rolling(20, min_periods=20).mean()
    roll_std = close.rolling(20, min_periods=20).std()
    df["bb_mid"] = roll_mean.round(2)
    df["bb_upper"] = (roll_mean + 2 * roll_std).round(2)
    df["bb_lower"] = (roll_mean - 2 * roll_std).round(2)

    band_width = df["bb_upper"] - df["bb_lower"]
    with np.errstate(divide="ignore", invalid="ignore"):
        pct_b = (close - df["bb_lower"]) / band_width
        pct_b[band_width == 0] = np.nan
    df["%b"] = pct_b.round(4)


def _add_rsi_wilder(df: pd.DataFrame, close: pd.Series, period: int = 14) -> None:
    """RSI chuẩn Wilder (EMA thay vì SMA)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = (100.0 - 100.0 / (1.0 + rs)).round(2)


def _add_macd(df: pd.DataFrame, close: pd.Series) -> None:
    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    macd_line = ema12 - ema26
    macd_signal = macd_line.ewm(span=9, adjust=False, min_periods=9).mean()

    df["macd"] = macd_line.round(2)
    df["macd_signal"] = macd_signal.round(2)
    df["macd_hist"] = (macd_line - macd_signal).round(2)


def _add_adx(df: pd.DataFrame, period: int = 14) -> None:
    """ADX/DI với làm mịn Wilder (EMA)."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = np.where((up_move > 0) & (up_move > down_move), up_move, 0.0)
    minus_dm = np.where((down_move > 0) & (down_move > up_move), down_move, 0.0)

    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)

    atr = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    smooth_plus = plus_dm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    smooth_minus = minus_dm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    # Tránh chia cho 0
    atr_val = atr.to_numpy()
    di_plus = np.divide(100.0 * smooth_plus.to_numpy(), atr_val,
                        out=np.zeros_like(atr_val), where=(atr_val != 0))
    di_minus = np.divide(100.0 * smooth_minus.to_numpy(), atr_val,
                         out=np.zeros_like(atr_val), where=(atr_val != 0))

    di_sum = di_plus + di_minus
    dx = np.divide(100.0 * np.abs(di_plus - di_minus), di_sum,
                   out=np.zeros_like(di_sum), where=(di_sum != 0))
    dx = pd.Series(dx, index=df.index)
    adx = dx.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    df["adx"] = adx.round(2)
    df["di_plus"] = pd.Series(di_plus, index=df.index).round(2)
    df["di_minus"] = pd.Series(di_minus, index=df.index).round(2)
    df["atr"] = atr.round(2)


def _add_ichimoku(df: pd.DataFrame) -> None:
    """Ichimoku Cloud (5 đường)."""
    high = df["high"]
    low = df["low"]
    close = df["close"]

    tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2.0
    kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2.0
    senkou_a = ((tenkan + kijun) / 2.0).shift(26)
    senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2.0).shift(26)
    chikou = close.shift(-26)

    df["tenkan"] = tenkan.round(2)
    df["kijun"] = kijun.round(2)
    df["senkou_a"] = senkou_a.round(2)
    df["senkou_b"] = senkou_b.round(2)
    df["chikou"] = chikou.round(2)


def _add_smc(df: pd.DataFrame) -> None:
    """Smart Money Concepts: Swing High/Low, BOS, CHoCH, Order Block."""
    high_arr = df["high"].to_numpy()
    low_arr = df["low"].to_numpy()
    open_arr = df["open"].to_numpy()
    close_arr = df["close"].to_numpy()
    n = len(high_arr)

    # Swing High / Low
    swing_high = np.zeros(n, dtype=bool)
    swing_low = np.zeros(n, dtype=bool)
    if n >= 3:
        swing_high[1:-1] = (high_arr[1:-1] > high_arr[:-2]) & (high_arr[1:-1] > high_arr[2:])
        swing_low[1:-1] = (low_arr[1:-1] < low_arr[:-2]) & (low_arr[1:-1] < low_arr[2:])

    # BOS & CHoCH
    bos_bull = np.zeros(n, dtype=bool)
    bos_bear = np.zeros(n, dtype=bool)
    choch_bull = np.zeros(n, dtype=bool)
    choch_bear = np.zeros(n, dtype=bool)

    last_sh = np.nan
    prev_sh = np.nan
    last_sl = np.nan
    prev_sl = np.nan
    sh_broken = False
    sl_broken = False
    trend = 0

    for i in range(1, n):
        if swing_high[i - 1]:
            prev_sh, last_sh = last_sh, high_arr[i - 1]
            sh_broken = False
            if (not np.isnan(prev_sh) and not np.isnan(last_sh) and
                    not np.isnan(prev_sl) and not np.isnan(last_sl)):
                if last_sh > prev_sh and last_sl > prev_sl:
                    trend = 1
                elif last_sh < prev_sh and last_sl < prev_sl:
                    trend = -1
        if swing_low[i - 1]:
            prev_sl, last_sl = last_sl, low_arr[i - 1]
            sl_broken = False
            if (not np.isnan(prev_sh) and not np.isnan(last_sh) and
                    not np.isnan(prev_sl) and not np.isnan(last_sl)):
                if last_sh > prev_sh and last_sl > prev_sl:
                    trend = 1
                elif last_sh < prev_sh and last_sl < prev_sl:
                    trend = -1

        if not np.isnan(last_sh) and not sh_broken and high_arr[i] > last_sh:
            sh_broken = True
            if trend == 1:
                bos_bull[i] = True
            elif trend == -1:
                choch_bull[i] = True
            else:
                bos_bull[i] = True

        if not np.isnan(last_sl) and not sl_broken and low_arr[i] < last_sl:
            sl_broken = True
            if trend == -1:
                bos_bear[i] = True
            elif trend == 1:
                choch_bear[i] = True
            else:
                bos_bear[i] = True

    # Order Block (OB)
    ob_bull = np.zeros(n, dtype=bool)
    ob_bear = np.zeros(n, dtype=bool)
    ob_high = np.full(n, np.nan, dtype=float)
    ob_low = np.full(n, np.nan, dtype=float)

    if n >= 4:
        is_bear = close_arr < open_arr
        is_bull = close_arr > open_arr
        ob_bull[:-3] = is_bear[:-3] & is_bull[1:-2] & is_bull[2:-1] & is_bull[3:]
        ob_bear[:-3] = is_bull[:-3] & is_bear[1:-2] & is_bear[2:-1] & is_bear[3:]
        ob_high[ob_bull | ob_bear] = high_arr[ob_bull | ob_bear]
        ob_low[ob_bull | ob_bear] = low_arr[ob_bull | ob_bear]

    df["swing_high"] = swing_high
    df["swing_low"] = swing_low
    df["bos_bull"] = bos_bull
    df["bos_bear"] = bos_bear
    df["choch_bull"] = choch_bull
    df["choch_bear"] = choch_bear
    df["ob_bull"] = ob_bull
    df["ob_bear"] = ob_bear
    df["ob_high"] = ob_high
    df["ob_low"] = ob_low


# ─────────────────────────────────────────────────────────────────────
# Hàm tổng hợp chỉ báo cho DataFrame có cột symbol (hoặc không)
# ─────────────────────────────────────────────────────────────────────

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tính tất cả chỉ báo kỹ thuật cho dữ liệu OHLCV.

    Parameters
    ----------
    df : pd.DataFrame
        Cần có cột: time, open, high, low, close.
        Nếu có cột 'symbol', sẽ tính riêng cho từng mã (groupby).
        Dữ liệu phải được sắp xếp thời gian tăng dần trong mỗi nhóm.

    Returns
    -------
    pd.DataFrame
        DataFrame với đầy đủ cột chỉ báo (ma20,...,adx, ichimoku..., smc...)
    """
    df = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df["time"]):
        df["time"] = pd.to_datetime(df["time"])

    has_symbol = "symbol" in df.columns
    group_col = "symbol" if has_symbol else "_temp_symbol"
    if not has_symbol:
        df["_temp_symbol"] = "SINGLE"

    parts = []
    for _, g in df.groupby(group_col, observed=True, sort=False):
        g = g.sort_values("time")
        close = g["close"]

        _add_ma(g, close)
        _add_bollinger(g, close)
        _add_rsi_wilder(g, close)
        _add_macd(g, close)
        _add_adx(g)
        _add_ichimoku(g)
        _add_smc(g)

        parts.append(g)

    result = pd.concat(parts, ignore_index=True)
    if "_temp_symbol" in result.columns:
        result.drop(columns=["_temp_symbol"], inplace=True)

    log.info("Đã tính xong chỉ báo cho %d dòng.", len(result))
    return result


# ─────────────────────────────────────────────────────────────────────
# Tạo tín hiệu giao dịch (đầy đủ thông tin cho Gemini)
# ─────────────────────────────────────────────────────────────────────

def _get_close_year_ago(df: pd.DataFrame, last_time: pd.Timestamp) -> Optional[float]:
    target = last_time - pd.DateOffset(years=1)
    idx = df["time"].searchsorted(target, side="right") - 1
    if idx >= 0:
        return df["close"].iloc[idx]
    return None


def build_signal(df: pd.DataFrame) -> dict:
    """
    Tạo tín hiệu tổng hợp từ 2 phiên cuối của một mã.

    Returns
    -------
    dict
        Bao gồm thông tin cơ bản, RSI, MACD, ADX, Ichimoku, SMC (dạng text).
    """
    if len(df) < 2:
        raise ValueError("Cần ít nhất 2 phiên để tạo tín hiệu.")

    last = df.iloc[-1]
    prev = df.iloc[-2]
    close = float(last["close"])
    chg_1d = (close - float(prev["close"])) / float(prev["close"]) * 100

    # Thay đổi 1 năm
    chg_1y = None
    try:
        prev_close_1y = _get_close_year_ago(df, last["time"])
        if prev_close_1y is not None and prev_close_1y != 0:
            chg_1y = (close - prev_close_1y) / prev_close_1y * 100
    except Exception:
        log.warning("Không tính được change_1y", exc_info=True)

    # MA trend
    if pd.notna(last["ma50"]) and pd.notna(last["ma200"]):
        ma_trend = "Tăng (Bullish)" if last["ma50"] > last["ma200"] else "Giảm (Bearish)"
    else:
        ma_trend = "Không xác định"

    # MACD
    macd_val = last["macd"]
    macd_sig = last["macd_signal"]
    prev_macd = prev["macd"]
    prev_sig = prev["macd_signal"]
    if all(pd.notna(x) for x in [macd_val, macd_sig, prev_macd, prev_sig]):
        if macd_val > macd_sig and prev_macd <= prev_sig:
            macd_status = "Golden cross (Bullish)"
        elif macd_val < macd_sig and prev_macd >= prev_sig:
            macd_status = "Death cross (Bearish)"
        elif macd_val > macd_sig:
            macd_status = "MACD trên Signal (Bullish)"
        else:
            macd_status = "MACD dưới Signal (Bearish)"
    else:
        macd_status = "Không đủ dữ liệu MACD"

    # RSI
    rsi = last["rsi"]
    if pd.isna(rsi):
        rsi_status = "Không đủ dữ liệu"
    else:
        rsi = float(rsi)
        if rsi > 70:
            rsi_status = f"Quá mua ({rsi:.1f})"
        elif rsi < 30:
            rsi_status = f"Quá bán ({rsi:.1f})"
        else:
            rsi_status = f"Trung tính ({rsi:.1f})"

    # Bollinger
    if pd.notna(last["bb_upper"]) and pd.notna(last["bb_lower"]):
        if close > last["bb_upper"]:
            bb_status = "Giá vượt dải BB trên — có thể quá mua"
        elif close < last["bb_lower"]:
            bb_status = "Giá phá dải BB dưới — có thể quá bán"
        else:
            bb_status = f"Trong dải Bollinger (%B={last['%b']:.2f})"
    else:
        bb_status = "Không đủ dữ liệu Bollinger"

    # ADX
    adx_val = last["adx"]
    if pd.notna(adx_val):
        adx_val = float(adx_val)
        if adx_val > 25:
            adx_trend = "Xu hướng mạnh"
        elif adx_val > 20:
            adx_trend = "Xu hướng yếu"
        else:
            adx_trend = "Không xu hướng (Sideways)"
        di_plus = float(last["di_plus"]) if pd.notna(last["di_plus"]) else 0
        di_minus = float(last["di_minus"]) if pd.notna(last["di_minus"]) else 0
        if di_plus > di_minus:
            adx_dir = "Tăng (DI+ > DI-)"
        elif di_minus > di_plus:
            adx_dir = "Giảm (DI- > DI+)"
        else:
            adx_dir = "Cân bằng"
        adx_status = f"{adx_trend}, {adx_dir}, ADX={adx_val:.1f}"
    else:
        adx_status = "Không đủ dữ liệu ADX"

    # Ichimoku
    tenkan = last["tenkan"]
    kijun = last["kijun"]
    senkou_a = last["senkou_a"]
    senkou_b = last["senkou_b"]
    if pd.notna(tenkan) and pd.notna(kijun) and pd.notna(senkou_a) and pd.notna(senkou_b):
        ichi = []
        if close > max(senkou_a, senkou_b):
            ichi.append("Giá trên mây (Bullish)")
        elif close < min(senkou_a, senkou_b):
            ichi.append("Giá dưới mây (Bearish)")
        else:
            ichi.append("Giá trong mây (Sideways)")
        if tenkan > kijun:
            ichi.append("Tenkan > Kijun (tín hiệu tăng)")
        elif tenkan < kijun:
            ichi.append("Tenkan < Kijun (tín hiệu giảm)")
        else:
            ichi.append("Tenkan = Kijun")
        ichimoku_status = "; ".join(ichi)
    else:
        ichimoku_status = "Không đủ dữ liệu Ichimoku"

    # SMC (tóm tắt sự kiện gần nhất)
    smc_events = []
    if last["bos_bull"]:
        smc_events.append("BOS Bull (phá vỡ cấu trúc tăng)")
    if last["bos_bear"]:
        smc_events.append("BOS Bear (phá vỡ cấu trúc giảm)")
    if last["choch_bull"]:
        smc_events.append("CHoCH Bull (đảo chiều sang tăng)")
    if last["choch_bear"]:
        smc_events.append("CHoCH Bear (đảo chiều sang giảm)")
    if last["ob_bull"]:
        smc_events.append(f"Bullish OB tại {last['ob_high']:.2f}-{last['ob_low']:.2f}")
    if last["ob_bear"]:
        smc_events.append(f"Bearish OB tại {last['ob_high']:.2f}-{last['ob_low']:.2f}")
    smc_status = "; ".join(smc_events) if smc_events else "Không tín hiệu SMC"

    signal = {
        "symbol": str(last.get("symbol", "")),
        "name": str(last.get("name", "")),
        "date": str(last["time"].date()),
        "close": round(close, 2),
        "change_1d": round(chg_1d, 2),
        "change_1y": round(chg_1y, 2) if chg_1y is not None else None,
        "ma_trend": ma_trend,
        "ma50": round(float(last["ma50"]), 2) if pd.notna(last["ma50"]) else None,
        "ma200": round(float(last["ma200"]), 2) if pd.notna(last["ma200"]) else None,
        "rsi": rsi_status,
        "macd": macd_status,
        "bollinger": bb_status,
        "adx": adx_status,
        "ichimoku": ichimoku_status,
        "smc": smc_status,
    }
    return signal


# ─────────────────────────────────────────────────────────────────────
# Hàm chạy hàng loạt cho dict các DataFrame (mỗi symbol một df)
# ─────────────────────────────────────────────────────────────────────

def run_all(frames: Dict[str, pd.DataFrame]) -> List[dict]:
    """
    Nhận dictionary {mã: DataFrame}, tính tất cả chỉ báo và trả về danh sách tín hiệu.
    """
    if not frames:
        return []

    df_list = []
    for symbol, df in frames.items():
        df_copy = df.copy()
        df_copy["symbol"] = symbol
        df_list.append(df_copy)

    all_df = pd.concat(df_list, ignore_index=True)
    all_df = compute_indicators(all_df)

    signals = []
    for symbol, g in all_df.groupby("symbol", sort=False):
        try:
            sig = build_signal(g)
            signals.append(sig)
            log.info("✅ %s (%s): close=%.2f RSI=%s", sig["name"], symbol, sig["close"], sig["rsi"])
        except Exception as e:
            log.error("Lỗi tạo tín hiệu %s: %s", symbol, e)
            continue

    return signals


# ─────────────────────────────────────────────────────────────────────
# Chạy thử
# ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
    csv_path = os.path.join(DATA_DIR, "VNMID.csv")

    logging.basicConfig(level=logging.INFO)

    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path, parse_dates=["time"])
        df["symbol"] = "VNMID"
        df = compute_indicators(df)
        print(build_signal(df))
    else:
        print("Chưa có data — chạy 01_fetch.py trước")
