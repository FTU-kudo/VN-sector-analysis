# 📊 VN Sector Indices Bot

Tự động phân tích kỹ thuật 11 chỉ số thị trường chứng khoán Việt Nam và gửi báo cáo hàng ngày qua Telegram.

## Chỉ số theo dõi

| Nhóm | Symbol | Tên |
|---|---|---|
| Vốn hoá | VNMID | VN Mid Cap |
| Vốn hoá | VNSML | VN Small Cap |
| Ngành | VNFIN | Tài chính |
| Ngành | VNREAL | Bất động sản |
| Ngành | VNIT | Công nghệ thông tin |
| Ngành | VNHEAL | Y tế |
| Ngành | VNENE | Năng lượng |
| Ngành | VNIND | Công nghiệp |
| Ngành | VNMAT | Nguyên vật liệu |
| Ngành | VNCONS | Tiêu dùng thiết yếu |
| Ngành | VNCOND | Tiêu dùng tùy ý |

## Kiến trúc

```
cron-job.org (08:00 GMT+7, T2-T6)
    → GitHub Actions
        → 01_fetch.py      # Lấy OHLCV từ vnstock VCI + cache CSV
        → 02_indicators.py # MA20/50/200, RSI, MACD, Bollinger Bands
        → 03_analysis.py   # Gemini Flash API phân tích tín hiệu
        → 04_telegram.py   # Gửi báo cáo qua Telegram Bot
```

## Setup

### 1. Tạo Telegram Bot
1. Nhắn `/newbot` cho [@BotFather](https://t.me/BotFather) → lấy **Bot Token**
2. Tạo channel hoặc group → thêm bot vào
3. Lấy **Chat ID**: gọi `https://api.telegram.org/bot<TOKEN>/getUpdates`

### 2. Lấy Gemini API Key
- Truy cập [Google AI Studio](https://aistudio.google.com/app/apikey) → tạo API Key miễn phí

### 3. Cấu hình GitHub Secrets
Vào **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Giá trị |
|---|---|
| `GEMINI_API_KEY` | API key từ Google AI Studio |
| `TELEGRAM_TOKEN` | Token từ BotFather |
| `TELEGRAM_CHAT_ID` | Chat ID của channel/group |

### 4. Setup cron-job.org (khuyến nghị)
1. Đăng ký tài khoản miễn phí tại [cron-job.org](https://cron-job.org)
2. Tạo cronjob mới:
   - **URL**: `https://api.github.com/repos/YOUR_USERNAME/YOUR_REPO/actions/workflows/main.yml/dispatches`
   - **Method**: POST
   - **Headers**: 
     ```
     Authorization: Bearer YOUR_GITHUB_PAT
     Accept: application/vnd.github.v3+json
     ```
   - **Body**: `{"ref":"main"}`
   - **Schedule**: Thứ 2–6, 08:00 (múi giờ GMT+7)

### 5. Chạy thử local
```bash
pip install -r requirements.txt

# Cấu hình biến môi trường
export GEMINI_API_KEY="your_key"
export TELEGRAM_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"

python src/main.py
```

## Cấu trúc repo

```
vn-sector-bot/
├── src/
│   ├── main.py          # Entry point pipeline
│   ├── 01_fetch.py      # Lấy dữ liệu vnstock
│   ├── 02_indicators.py # Tính chỉ báo kỹ thuật
│   ├── 03_analysis.py   # Gọi Gemini AI
│   └── 04_telegram.py   # Gửi Telegram
├── data/                # Cache CSV (auto-generated)
├── .github/
│   └── workflows/
│       └── main.yml
├── requirements.txt
└── README.md
```

## Mẫu tin nhắn Telegram

```
📊 BÁO CÁO THỊ TRƯỜNG — 04/08/2026

Vốn hoá trung – nhỏ
🟢 VNMID 1,913.2 (+2.14%) | RSI Trung tính
🔴 VNSML 1,250.0 (-0.73%) | RSI Quá bán

Chỉ số ngành
🟢 VNFIN  2,153.9 (+1.2%) | RSI Trung tính
...

━━━━━━━━━━━━━━━━━
🤖 Phân tích AI

[Phân tích tự động từ Gemini]
```
