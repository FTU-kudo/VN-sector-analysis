"""
03_analysis.py — Phân tích thị trường bằng Gemini Free API (prompt súc tích).
"""

import os
import json
import logging
from typing import List, Dict

import requests

log = logging.getLogger("analysis")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash-lite:generateContent"
)


def build_prompt(signals: List[dict]) -> str:
    """
    Tạo prompt cực ngắn gọn từ danh sách tín hiệu đã có.
    Chỉ truyền các thông tin cốt lõi: giá, thay đổi, RSI, ADX, Ichimoku, SMC.
    """
    # Phân nhóm vốn hoá / ngành
    cap_syms = {"VNMID", "VNSML"}
    cap_sigs = [s for s in signals if s["symbol"] in cap_syms]
    sector_sigs = [s for s in signals if s["symbol"] not in cap_syms]

    def fmt_signal(s: dict) -> str:
        # Dòng ngắn: symbol, close, 1D, RSI, ADX, Ichimoku (tóm tắt), SMC (nếu có)
        parts = [
            f"{s['name']} ({s['symbol']}): {s['close']:,.1f}",
            f"1D={s['change_1d']:+.1f}%",
        ]
        # RSI
        rsi_str = s['rsi']
        if "Quá mua" in rsi_str:
            rsi_str = "🟥" + rsi_str
        elif "Quá bán" in rsi_str:
            rsi_str = "🟩" + rsi_str
        parts.append(f"RSI={rsi_str}")

        # ADX
        adx_str = s.get("adx", "")
        if "mạnh" in adx_str.lower():
            adx_str = "ADX↑ " + adx_str
        elif "yếu" in adx_str.lower():
            adx_str = "ADX→ " + adx_str
        elif "không" in adx_str.lower():
            adx_str = "ADX↓ " + adx_str
        parts.append(adx_str if adx_str else "ADX=N/A")

        # Ichimoku (chỉ lấy trạng thái giá so với mây và tenkan/kijun)
        ichi = s.get("ichimoku", "")
        if ichi:
            # rút gọn
            if "Giá trên mây" in ichi:
                ichi_short = "☁️Trên"
            elif "Giá dưới mây" in ichi:
                ichi_short = "☁️Dưới"
            else:
                ichi_short = "☁️Trong"
            if "Tenkan > Kijun" in ichi:
                ichi_short += " TK↑"
            elif "Tenkan < Kijun" in ichi:
                ichi_short += " TK↓"
            parts.append(f"Ichi={ichi_short}")
        else:
            parts.append("Ichi=N/A")

        # SMC (nếu có tín hiệu)
        smc = s.get("smc", "")
        if smc and smc != "Không tín hiệu SMC":
            parts.append(f"SMC={smc[:50]}")  # cắt ngắn
        return " | ".join(parts)

    prompt = f"""Bạn là chuyên gia phân tích kỹ thuật thị trường chứng khoán Việt Nam.
Ngày: {signals[0]['date']}

## Chỉ số vốn hoá trung – nhỏ
{chr(10).join(fmt_signal(s) for s in cap_sigs)}

## Chỉ số ngành
{chr(10).join(fmt_signal(s) for s in sector_sigs)}

Viết báo cáo ngắn gọn (≤250 từ) bằng tiếng Việt:
1. Tổng quan thị trường (1-2 câu)
2. Nhóm ngành nổi bật nhất & yếu nhất
3. Cảnh báo kỹ thuật quan trọng (RSI cực đoan, ADX mạnh + hướng, Ichimoku, SMC)
4. Nhận định ngắn hạn (1 câu)

Không dùng markdown phức tạp, chỉ dùng **in đậm** cho tiêu đề."""
    return prompt


def call_gemini(prompt: str) -> str:
    """Gọi Gemini Free API, trả về văn bản phân tích."""
    if not GEMINI_API_KEY:
        log.warning("Chưa cấu hình GEMINI_API_KEY")
        return "⚠️ Chưa cấu hình GEMINI_API_KEY."

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 600,
        },
    }
    try:
        resp = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except requests.RequestException as e:
        log.error("Lỗi Gemini API: %s", e)
        return f"❌ Lỗi Gemini API: {e}"
    except (KeyError, IndexError) as e:
        log.error("Phản hồi không hợp lệ: %s", resp.text[:200])
        return f"❌ Phản hồi Gemini không hợp lệ: {resp.text[:200]}"


def analyze(signals: List[dict]) -> str:
    """Từ danh sách tín hiệu (có ADX, Ichimoku, SMC) → phân tích Gemini."""
    if not signals:
        return "Không có dữ liệu tín hiệu."
    prompt = build_prompt(signals)
    log.info("Prompt length: %d chars", len(prompt))
    return call_gemini(prompt)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Test với dữ liệu giả có đủ các trường mới
    dummy = [
        {
            "symbol": "VNMID", "name": "VN Mid Cap", "date": "2026-08-03",
            "close": 1913.2, "change_1d": 2.12, "change_1y": 8.2,
            "ma_trend": "Tăng (Bullish)", "ma50": 1850.0, "ma200": 1780.0,
            "rsi": "Trung tính (52.3)",
            "macd": "MACD trên Signal (Bullish)",
            "bollinger": "Trong dải Bollinger (%B=0.62)",
            "adx": "Xu hướng mạnh, Tăng (DI+ > DI-), ADX=28.5",
            "ichimoku": "Giá trên mây (Bullish); Tenkan > Kijun (tín hiệu tăng)",
            "smc": "Không tín hiệu SMC"
        },
        {
            "symbol": "VNREAL", "name": "VN Bất động sản", "date": "2026-08-03",
            "close": 3106.8, "change_1d": 0.03, "change_1y": -5.1,
            "rsi": "Quá bán (28.4)",
            "adx": "Xu hướng yếu, Giảm (DI- > DI+), ADX=22.0",
            "ichimoku": "Giá dưới mây (Bearish); Tenkan < Kijun (tín hiệu giảm)",
            "smc": "BOS Bear (phá vỡ cấu trúc giảm)"
        }
    ]
    print(analyze(dummy))
