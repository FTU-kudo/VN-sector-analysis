"""
04_telegram.py — Format và gửi báo cáo thị trường qua Telegram.
- Chuyển đổi markdown **bold** từ Gemini thành HTML <b>bold</b>.
- Giữ nguyên tất cả thuật ngữ kỹ thuật (BOS, CHoCH, v.v.).
"""

import os
import logging
import re
from typing import List, Dict

import requests

log = logging.getLogger("telegram")

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_URL     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"


def _markdown_to_html(text: str) -> str:
    """
    Chuyển **bold** → <b>bold</b>.
    Không hỗ trợ các markdown khác.
    """
    # Dùng regex đơn giản để thay thế cặp **...**
    return re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)


# ── Các hàm rút gọn chỉ báo (giữ nguyên) ──────────────────────────
def _rsi_label(rsi_str: str) -> str:
    if not rsi_str:
        return "N/A"
    return rsi_str

def _macd_format(macd_str: str, macd_line_val: float) -> str:
    if not macd_str:
        return "N/A"
    if "Golden" in macd_str:
        status = "Golden ✨"
    elif "Death" in macd_str:
        status = "Death 💀"
    elif "Bullish" in macd_str:
        status = "Bullish"
    elif "Bearish" in macd_str:
        status = "Bearish"
    else:
        status = macd_str[:12]
    if macd_line_val is not None:
        return f"{status} ({macd_line_val:+.2f})"
    return status

def _adx_format(adx_str: str) -> str:
    if not adx_str or "N/A" in adx_str:
        return "N/A"
    strength = ""
    direction_icon = ""
    adx_val = ""
    parts = adx_str.split(", ")
    for p in parts:
        if "mạnh" in p:
            strength = "Mạnh"
            strength_icon = "↑"
        elif "yếu" in p:
            strength = "Yếu"
            strength_icon = "→"
        elif "không" in p:
            strength = "Yếu"
            strength_icon = "↓"
        if "Tăng" in p:
            direction_icon = "📈"
        elif "Giảm" in p:
            direction_icon = "📉"
        if "ADX=" in p:
            adx_val = p.split("=")[-1]
    if not strength:
        return adx_str[:20]
    try:
        adx_num = float(adx_val)
    except ValueError:
        adx_num = None
    adx_str_fmt = f"{adx_num:.2f}" if adx_num is not None else adx_val
    return f"{strength} ({adx_str_fmt}){strength_icon}{direction_icon}"

def _ichimoku_format(ichi_str: str) -> str:
    if not ichi_str or "N/A" in ichi_str:
        return "N/A"
    if "Giá trên mây" in ichi_str and "Tenkan > Kijun" in ichi_str:
        outlook = "Tích cực"
    elif "Giá dưới mây" in ichi_str and "Tenkan < Kijun" in ichi_str:
        outlook = "Tiêu cực"
    elif "Giá trên mây" in ichi_str:
        outlook = "Tích cực"
    elif "Giá dưới mây" in ichi_str:
        outlook = "Tiêu cực"
    else:
        outlook = "Trung tính"
    cloud = "☁️↑" if "Giá trên mây" in ichi_str else ("☁️↓" if "Giá dưới mây" in ichi_str else "☁️→")
    tk = "TK↑" if "Tenkan > Kijun" in ichi_str else ("TK↓" if "Tenkan < Kijun" in ichi_str else "TK=")
    return f"{outlook} ({cloud} {tk})"

def _smc_short(smc_str: str) -> str:
    if not smc_str or "Không tín hiệu" in smc_str:
        return ""
    # Giữ nguyên CHoCH, BOS, OB
    for keyword in ["BOS Bull", "BOS Bear", "CHoCH Bull", "CHoCH Bear", "Bullish OB", "Bearish OB"]:
        if keyword in smc_str:
            return keyword
    return ""


# ── Format tin nhắn ─────────────────────────────────────────────────
def format_message(signals: List[dict], analysis: str) -> str:
    # Ngày từ dữ liệu
    if signals and "date" in signals[0]:
        date_str = signals[0]["date"]
    else:
        from datetime import datetime
        date_str = datetime.now().strftime("%d/%m/%Y")

    # Phân nhóm
    market_syms = {"VNINDEX", "VN30", "VN100", "VNALL", "HNXINDEX", "UPCOMINDEX"}
    cap_syms = {"VNMID", "VNSML"}
    market_sigs = [s for s in signals if s["symbol"] in market_syms]
    cap_sigs = [s for s in signals if s["symbol"] in cap_syms]
    sector_sigs = [s for s in signals if s["symbol"] not in market_syms and s["symbol"] not in cap_syms]

    def arrow(chg: float) -> str:
        return "🟢" if chg > 0 else ("🔴" if chg < 0 else "⚪")

    def fmt_row(s: dict) -> str:
        a = arrow(s["change_1d"])
        symbol = s.get("symbol", "???")
        close = s.get("close", 0)
        chg_1d = s.get("change_1d", 0)

        rsi_display = _rsi_label(s.get("rsi", ""))
        macd_display = _macd_format(s.get("macd", ""), s.get("macd_line"))
        adx_display = _adx_format(s.get("adx", ""))
        ichi_display = _ichimoku_format(s.get("ichimoku", ""))
        smc_display = _smc_short(s.get("smc", ""))

        line = f"{a} <b>{symbol}</b> {close:,.2f} ({chg_1d:+.2f}%)"
        details = [f"RSI: {rsi_display}", f"MACD: {macd_display}"]
        if adx_display != "N/A":
            details.append(f"ADX: {adx_display}")
        if ichi_display != "N/A":
            details.append(f"Ichi: {ichi_display}")
        if smc_display:
            details.append(f"SMC: {smc_display}")
        if details:
            line += " | " + " | ".join(details)
        return line

    market_lines = "\n".join(fmt_row(s) for s in market_sigs) if market_sigs else "—"
    cap_lines = "\n".join(fmt_row(s) for s in cap_sigs) if cap_sigs else "—"
    sector_lines = "\n".join(fmt_row(s) for s in sector_sigs) if sector_sigs else "—"

    # Chuyển đổi markdown → HTML cho phần phân tích của Gemini
    analysis_html = _markdown_to_html(analysis)

    msg = f"""📊 <b>BÁO CÁO THỊ TRƯỜNG — {date_str}</b>

📈 <b>Chỉ số thị trường chung</b>
{market_lines}

🏢 <b>Nhóm vốn hoá trung – nhỏ</b>
{cap_lines}

🏭 <b>Chỉ số ngành</b>
{sector_lines}

━━━━━━━━━━━━━━━━━
🤖 <b>Phân tích AI</b>

{analysis_html}

━━━━━━━━━━━━━━━━━
<i>Nguồn: vnstock</i>"""
    return msg


def send_telegram(message: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Chưa cấu hình TELEGRAM_TOKEN / TELEGRAM_CHAT_ID")
        return False

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Dữ liệu test
    dummy_signals = [
        {"symbol": "VNINDEX", "name": "VN-Index", "date": "2026-08-03",
         "close": 1280.56, "change_1d": 0.85,
         "rsi": "Trung tính (56.23)",
         "macd": "MACD trên Signal (Bullish)", "macd_line": 1.25,
         "adx": "Xu hướng yếu, Tăng (DI+ > DI-), ADX=22.10",
         "ichimoku": "Giá trên mây (Bullish); Tenkan > Kijun (tín hiệu tăng)",
         "smc": "BOS Bull (phá vỡ cấu trúc tăng)"},
        {"symbol": "VNMID", "name": "VN Mid Cap", "date": "2026-08-03",
         "close": 1913.20, "change_1d": 2.12,
         "rsi": "Trung tính (52.30)",
         "macd": "Golden cross (Bullish)", "macd_line": 0.85,
         "adx": "Xu hướng mạnh, Tăng (DI+ > DI-), ADX=28.50",
         "ichimoku": "Giá trên mây (Bullish); Tenkan > Kijun (tín hiệu tăng)",
         "smc": "CHoCH Bull (đảo chiều sang tăng)"},
    ]
    dummy_analysis = "**Tổng quan thị trường** hôm nay khá tích cực với tín hiệu CHoCH Bull từ VNMID."
    msg = format_message(dummy_signals, dummy_analysis)
    print(msg)
