"""
04_telegram.py — Format và gửi báo cáo thị trường đầy đủ qua Telegram.
Hiển thị: giá, 1D, RSI, MACD, ADX, Ichimoku, SMC.
"""

import os
import logging
from typing import List, Dict

import requests

log = logging.getLogger("telegram")

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_URL     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

# ── Hàm tiện ích rút gọn chỉ báo ──────────────────────────────────────

def _rsi_label(rsi_str: str) -> str:
    """Trả về chuỗi RSI dạng số + trạng thái ngắn (Quá mua, Quá bán, Trung tính)."""
    if not rsi_str:
        return "N/A"
    # Mẫu: "Trung tính (53.1)" -> "53.1 Trung tính"
    parts = rsi_str.split("(")
    state = parts[0].strip()
    val = parts[1].replace(")", "").strip() if len(parts) > 1 else "?"
    return f"{val} {state}"

def _macd_short(macd_str: str) -> str:
    """Rút gọn MACD: Bullish / Bearish / Golden / Death."""
    if "Golden" in macd_str:
        return "Golden ✨"
    if "Death" in macd_str:
        return "Death 💀"
    if "Bullish" in macd_str or "trên Signal" in macd_str.lower():
        return "Bullish"
    if "Bearish" in macd_str or "dưới Signal" in macd_str.lower():
        return "Bearish"
    return macd_str[:12]  # fallback

def _adx_short(adx_str: str) -> str:
    """ADX: lấy số ADX và hướng (↑/→/↓)."""
    if not adx_str or "N/A" in adx_str:
        return "N/A"
    # Mẫu: "Xu hướng mạnh, Tăng (DI+ > DI-), ADX=28.5"
    parts = adx_str.split(", ")
    strength = ""
    direction = ""
    adx_val = ""
    for p in parts:
        if "mạnh" in p:
            strength = "↑"
        elif "yếu" in p:
            strength = "→"
        elif "không" in p:
            strength = "↓"
        if "Tăng" in p:
            direction = "📈"
        elif "Giảm" in p:
            direction = "📉"
        if "ADX=" in p:
            adx_val = p.split("=")[-1]
    return f"{adx_val}{strength}{direction}"

def _ichi_short(ichi_str: str) -> str:
    """Ichimoku: ☁️ trên/dưới + TK ↑/↓."""
    if not ichi_str or "N/A" in ichi_str:
        return "N/A"
    cloud = ""
    if "Giá trên mây" in ichi_str:
        cloud = "☁️↑"
    elif "Giá dưới mây" in ichi_str:
        cloud = "☁️↓"
    else:
        cloud = "☁️→"
    tk = ""
    if "Tenkan > Kijun" in ichi_str:
        tk = "TK↑"
    elif "Tenkan < Kijun" in ichi_str:
        tk = "TK↓"
    return f"{cloud} {tk}"

def _smc_short(smc_str: str) -> str:
    """SMC: chỉ lấy sự kiện chính (BOS/CHoCH)."""
    if not smc_str or "Không tín hiệu" in smc_str:
        return ""
    # Ưu tiên BOS/CHoCH
    for keyword in ["BOS Bull", "BOS Bear", "CHoCH Bull", "CHoCH Bear"]:
        if keyword in smc_str:
            return keyword
    # Nếu có OB
    if "Bullish OB" in smc_str:
        return "OB Bull"
    if "Bearish OB" in smc_str:
        return "OB Bear"
    return smc_str[:20]

# ── Format tin nhắn Telegram ───────────────────────────────────────────

def format_message(signals: List[dict], analysis: str) -> str:
    """Tạo tin nhắn Telegram hoàn chỉnh với đầy đủ tín hiệu."""
    # Ngày từ dữ liệu
    if signals and "date" in signals[0]:
        date_str = signals[0]["date"]
    else:
        from datetime import datetime
        date_str = datetime.now().strftime("%d/%m/%Y")

    # Phân nhóm
    market_syms = {"VNINDEX", "VN30", "VN100", "VNALL"}
    cap_syms    = {"VNMID", "VNSML"}
    market_sigs = [s for s in signals if s["symbol"] in market_syms]
    cap_sigs    = [s for s in signals if s["symbol"] in cap_syms]
    sector_sigs = [s for s in signals if s["symbol"] not in market_syms and s["symbol"] not in cap_syms]

    def arrow(chg: float) -> str:
        return "🟢" if chg > 0 else ("🔴" if chg < 0 else "⚪")

    def fmt_row(s: dict) -> str:
        a = arrow(s["change_1d"])
        symbol = s.get("symbol", "???")
        close  = s.get("close", 0)
        chg_1d = s.get("change_1d", 0)
        rsi    = _rsi_label(s.get("rsi", ""))
        macd   = _macd_short(s.get("macd", ""))
        adx    = _adx_short(s.get("adx", ""))
        ichi   = _ichi_short(s.get("ichimoku", ""))
        smc    = _smc_short(s.get("smc", ""))

        # Xây dựng dòng
        line = f"{a} <b>{symbol}</b> {close:,.1f} ({chg_1d:+.2f}%)"
        details = []
        details.append(f"RSI:{rsi}")
        details.append(f"MACD:{macd}")
        if adx != "N/A": details.append(f"ADX:{adx}")
        if ichi != "N/A": details.append(f"Ichi:{ichi}")
        if smc: details.append(f"SMC:{smc}")
        if details:
            line += " | " + " | ".join(details)
        return line

    market_lines = "\n".join(fmt_row(s) for s in market_sigs) if market_sigs else "—"
    cap_lines    = "\n".join(fmt_row(s) for s in cap_sigs) if cap_sigs else "—"
    sector_lines = "\n".join(fmt_row(s) for s in sector_sigs) if sector_sigs else "—"

    msg = f"""📊 <b>BÁO CÁO THỊ TRƯỜNG — {date_str}</b>

<b>Chỉ số thị trường chung</b>
{market_lines}

<b>Vốn hoá trung – nhỏ</b>
{cap_lines}

<b>Chỉ số ngành</b>
{sector_lines}

━━━━━━━━━━━━━━━━━
🤖 <b>Phân tích AI</b>

{analysis}

━━━━━━━━━━━━━━━━━
<i>Nguồn: vnstock · Phân tích: Gemini Flash</i>"""
    return msg


def send_telegram(message: str) -> bool:
    """Gửi tin nhắn Telegram (HTML)."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Chưa cấu hình TELEGRAM_TOKEN / TELEGRAM_CHAT_ID")
        return False

    payload = {
        "chat_id":                  TELEGRAM_CHAT_ID,
        "text":                     message,
        "parse_mode":               "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(TELEGRAM_URL, json=payload, timeout=15)
        resp.raise_for_status()
        log.info("Đã gửi Telegram thành công")
        return True
    except requests.RequestException as e:
        log.error("Lỗi gửi Telegram: %s", e)
        return False


# ── Test cục bộ ────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    dummy_signals = [
        {
            "symbol": "VNINDEX", "name": "VN-Index", "date": "2026-08-03",
            "close": 1280.5, "change_1d": 0.85,
            "rsi": "Trung tính (56.2)",
            "macd": "MACD trên Signal (Bullish)",
            "adx": "Xu hướng yếu, Tăng (DI+ > DI-), ADX=22.1",
            "ichimoku": "Giá trên mây (Bullish); Tenkan > Kijun (tín hiệu tăng)",
            "smc": "Không tín hiệu SMC"
        },
        {
            "symbol": "VNMID", "name": "VN Mid Cap", "date": "2026-08-03",
            "close": 1913.2, "change_1d": 2.12,
            "rsi": "Trung tính (52.3)",
            "macd": "Golden cross (Bullish)",
            "adx": "Xu hướng mạnh, Tăng (DI+ > DI-), ADX=28.5",
            "ichimoku": "Giá trên mây (Bullish); Tenkan > Kijun (tín hiệu tăng)",
            "smc": "BOS Bull (phá vỡ cấu trúc tăng)"
        },
        {
            "symbol": "VNSML", "name": "VN Small Cap", "date": "2026-08-03",
            "close": 1250.0, "change_1d": -0.73,
            "rsi": "Quá bán (28.9)",
            "macd": "Death cross (Bearish)",
            "adx": "Xu hướng mạnh, Giảm (DI- > DI+), ADX=30.2",
            "ichimoku": "Giá dưới mây (Bearish); Tenkan < Kijun (tín hiệu giảm)",
            "smc": "BOS Bear (phá vỡ cấu trúc giảm)"
        },
        {
            "symbol": "VNREAL", "name": "VN Bất động sản", "date": "2026-08-03",
            "close": 3106.8, "change_1d": 0.03,
            "rsi": "Quá bán (28.4)",
            "macd": "MACD dưới Signal (Bearish)",
            "adx": "Xu hướng yếu, Giảm (DI- > DI+), ADX=19.5",
            "ichimoku": "Giá trong mây (Sideways); Tenkan < Kijun (tín hiệu giảm)",
            "smc": "Không tín hiệu SMC"
        }
    ]
    dummy_analysis = "Đây là phân tích mẫu từ Gemini."
    msg = format_message(dummy_signals, dummy_analysis)
    print(msg)
