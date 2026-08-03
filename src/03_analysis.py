"""
03_analysis.py — Phân tích thị trường bằng Gemini Free API
"""

import os
import json
import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL     = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-3.1-flash-lite:generateContent"
)


def build_prompt(signals: list[dict]) -> str:
    """Tạo prompt từ danh sách tín hiệu kỹ thuật."""

    # Tách nhóm vốn hoá vs ngành
    cap_syms    = {"VNMID", "VNSML"}
    cap_sigs    = [s for s in signals if s["symbol"] in cap_syms]
    sector_sigs = [s for s in signals if s["symbol"] not in cap_syms]

    def fmt_group(sigs: list[dict]) -> str:
        lines = []
        for s in sigs:
            chg_1y = f"{s['change_1y']:+.1f}%" if s["change_1y"] else "N/A"
            lines.append(
                f"• {s['name']} ({s['symbol']}): "
                f"close={s['close']:,.1f} | "
                f"1D={s['change_1d']:+.1f}% | "
                f"1Y={chg_1y} | "
                f"Trend={s['ma_trend']} | "
                f"RSI={s['rsi']} | "
                f"MACD={s['macd']} | "
                f"BB={s['bollinger']}"
            )
        return "\n".join(lines)

    prompt = f"""Bạn là chuyên gia phân tích kỹ thuật thị trường chứng khoán Việt Nam.
Dưới đây là tín hiệu kỹ thuật cuối phiên ngày {signals[0]['date']}.

## Chỉ số vốn hoá trung – nhỏ
{fmt_group(cap_sigs)}

## Chỉ số theo nhóm ngành
{fmt_group(sector_sigs)}

Hãy viết một bản phân tích ngắn gọn (khoảng 250–350 từ) theo cấu trúc:
1. **Tổng quan thị trường** — xu hướng chung Mid/Small cap
2. **Nhóm ngành nổi bật** — điểm sáng và nhóm yếu nhất
3. **Tín hiệu cần chú ý** — cảnh báo RSI, MACD cross, phá BB
4. **Nhận định ngắn hạn** — 1 câu tóm tắt định hướng

Viết bằng tiếng Việt, ngắn gọn, chuyên nghiệp. Không dùng markdown quá phức tạp."""
    return prompt


def call_gemini(prompt: str) -> str:
    if not GEMINI_API_KEY:
        return "⚠️ Chưa cấu hình GEMINI_API_KEY."

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature":    0.4,
            "maxOutputTokens": 600,
        },
    }
    try:
        resp = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json=payload, timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except requests.RequestException as e:
        return f"❌ Lỗi Gemini API: {e}"
    except (KeyError, IndexError):
        return f"❌ Phản hồi Gemini không hợp lệ: {resp.text[:200]}"


def analyze(signals: list[dict]) -> str:
    """Nhận list signals → trả về chuỗi phân tích từ Gemini."""
    prompt   = build_prompt(signals)
    analysis = call_gemini(prompt)
    return analysis


if __name__ == "__main__":
    # Test với dữ liệu giả
    dummy = [
        {"symbol": "VNMID", "name": "VN Mid Cap", "date": "2026-08-03",
         "close": 1900.0, "change_1d": 0.5, "change_1y": 8.2,
         "ma_trend": "Tăng (Bullish)", "ma50": 1850.0, "ma200": 1780.0,
         "rsi": "Trung tính (52.3)", "macd": "MACD trên Signal (Bullish)",
         "bollinger": "Trong dải Bollinger (%B=0.62)"},
    ]
    print(build_prompt(dummy))
