"""
04_telegram.py — Format và gửi báo cáo qua Telegram
"""

import os
import requests

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_URL     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"


def format_message(signals: list[dict], analysis: str) -> str:
    """Tạo tin nhắn Telegram từ signals + phân tích Gemini."""
    from datetime import datetime
    today = datetime.now().strftime("%d/%m/%Y")

    cap_syms    = {"VNMID", "VNSML"}
    cap_sigs    = [s for s in signals if s["symbol"] in cap_syms]
    sector_sigs = [s for s in signals if s["symbol"] not in cap_syms]

    def arrow(chg: float) -> str:
        return "🟢" if chg > 0 else ("🔴" if chg < 0 else "⚪")

    def fmt_row(s: dict) -> str:
        a = arrow(s["change_1d"])
        return (f"{a} <b>{s['symbol']}</b> {s['close']:,.1f} "
                f"({s['change_1d']:+.2f}%) | RSI {s['rsi'].split('(')[0].strip()}")

    cap_lines    = "\n".join(fmt_row(s) for s in cap_sigs)
    sector_lines = "\n".join(fmt_row(s) for s in sector_sigs)

    msg = f"""📊 <b>BÁO CÁO THỊ TRƯỜNG — {today}</b>

<b>Vốn hoá trung – nhỏ</b>
{cap_lines}

<b>Chỉ số ngành</b>
{sector_lines}

━━━━━━━━━━━━━━━━━
🤖 <b>Phân tích AI</b>

{analysis}

━━━━━━━━━━━━━━━━━
<i>Nguồn: vnstock VCI · Phân tích: Gemini Flash</i>"""
    return msg


def send_telegram(message: str) -> bool:
    """Gửi tin nhắn Telegram, trả về True nếu thành công."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️  Chưa cấu hình TELEGRAM_TOKEN / TELEGRAM_CHAT_ID")
        return False

    payload = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(TELEGRAM_URL, json=payload, timeout=15)
        resp.raise_for_status()
        print("✅ Đã gửi Telegram thành công")
        return True
    except requests.RequestException as e:
        print(f"❌ Lỗi gửi Telegram: {e}")
        return False


if __name__ == "__main__":
    # Test format (không gửi thật)
    dummy_signals  = [
        {"symbol": "VNMID", "name": "VN Mid Cap", "date": "2026-08-03",
         "close": 1913.16, "change_1d": 2.14, "change_1y": 8.2,
         "ma_trend": "Tăng (Bullish)", "ma50": 1850.0, "ma200": 1780.0,
         "rsi": "Trung tính (53.1)", "macd": "MACD trên Signal (Bullish)",
         "bollinger": "Trong dải Bollinger (%B=0.65)"},
        {"symbol": "VNSML", "name": "VN Small Cap", "date": "2026-08-03",
         "close": 1250.02, "change_1d": -0.73, "change_1y": 3.5,
         "ma_trend": "Giảm (Bearish)", "ma50": 1280.0, "ma200": 1300.0,
         "rsi": "Quá bán (28.9)", "macd": "MACD dưới Signal (Bearish)",
         "bollinger": "Giá phá dải BB dưới — có thể quá bán"},
    ]
    dummy_analysis = "Đây là phân tích mẫu từ Gemini AI."
    msg = format_message(dummy_signals, dummy_analysis)
    print(msg)
