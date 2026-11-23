<!-- README.md -->
# 📊 VN Sector Indices Bot

Tự động phân tích kỹ thuật các chỉ số thị trường chứng khoán Việt Nam và gửi báo cáo hàng ngày qua Telegram.

Dữ liệu OHLCV lấy từ **nguồn dữ liệu thị trường đã mua** (xem `src/yuanta_client.py`). Thư viện `vnstock`/VCI đã được
loại bỏ hoàn toàn — nguồn đó không còn cung cấp dữ liệu, và mọi phụ thuộc vào index cài đặt riêng của nó đã bị xoá khỏi
`requirements.txt`.

## Chỉ số theo dõi

| Nhóm | Symbol | Tên |
|---|---|---|
| Thị trường | VNINDEX | VN-Index |
| Thị trường | VN30 | VN30 |
| Thị trường | VN100 | VN100 |
| Thị trường | VNALL | VN All Share |
| Thị trường | HNXINDEX | HNX-Index |
| Thị trường | UPCOMINDEX | UPCOM-Index |
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
| Ngành | VNUTI | Tiện ích |

## Kiến trúc

```
cron-job.org (17:15 GMT+7, T2-T6)
    → GitHub Actions
        → pytest                        # 57 test: parser, timestamp, chống bot, làm sạch dữ liệu
        → 01_fetch.py   # OHLCV từ nguồn đã mua + cache CSV + quality_report.json
        → 02_indicators.py # MA20/50/200, RSI, MACD, Bollinger, ADX, Ichimoku, SMC
        → 03_analysis.py   # Gemini Flash API phân tích tín hiệu
        → 04_telegram.py   # Gửi báo cáo qua Telegram Bot
        → commit CSV + quality_report.json
        → check_freshness.py            # chặn trường hợp dữ liệu âm thầm đứng yên
```

Nếu bất kỳ bước nào lỗi, bước `Alert on failure` gửi tin nhắn Telegram báo hỏng — kể cả khi lỗi xảy ra ở
`pip install` (script dùng `urllib` thuần, không phụ thuộc gói ngoài).

## Cấu trúc repo

```
src/
├── main.py             # Entry point pipeline (--force-full, --symbols)
├── yuanta_client.py    # HTTP client: nến ngày + bảng chỉ số, xử lý challenge, retry
├── data_quality.py     # Quy tắc kiểm tra/làm sạch nến (nguồn sự thật duy nhất)
├── 01_fetch.py         # Tải dữ liệu, ghép với cache, ghi quality_report.json
├── 02_indicators.py    # Tính chỉ báo kỹ thuật
├── 03_analysis.py      # Gọi Gemini AI
├── 04_telegram.py      # Format + gửi Telegram
├── repair_data.py      # Làm sạch CSV đã commit (một lần / khi cần)
├── check_freshness.py  # Cảnh báo & fail khi dữ liệu quá cũ
└── notify_failure.py   # Cảnh báo Telegram khi workflow lỗi (chỉ stdlib)
tests/                  # 57 test, không cần mạng
data/                   # Cache CSV + quality_report.json (commit vào repo)
```

## Quy tắc dữ liệu

Mỗi nến đi qua `data_quality.sanitize_bars` trước khi được ghi:

| Tình huống | Xử lý |
|---|---|
| Nến rơi vào Thứ 7 / Chủ nhật | loại bỏ |
| Nến của hôm nay trước 15:15 giờ VN | loại bỏ (phiên chưa đóng) |
| Nến ở tương lai | loại bỏ |
| Giá ≤ 0 hoặc không phải số | loại bỏ |
| `close` nằm ngoài `[low, high]` | nới `low`/`high` cho bao được `close` |
| `open` nằm ngoài `[low, high]` | kéo `open` về trong khoảng (nguồn hay giữ nguyên `open` cũ nhiều phiên) |
| Trùng ngày | giữ bản mới nhất |

Lịch sử chỉ được **ghép thêm**, không bao giờ bị cắt bớt; 15 ngày gần nhất được tải lại mỗi lần chạy để nhận điều
chỉnh muộn. Nếu nguồn trả về dữ liệu cũ hơn cache, bot giữ cache và ghi cảnh báo. Mọi sửa đổi được ghi vào
`data/quality_report.json` (kèm so sánh chéo với bảng chỉ số).

## Setup

### 1. Secrets
**Settings → Secrets and variables → Actions → New repository secret:**

| Secret | Giá trị |
|---|---|
| `GEMINI_API_KEY` | API key từ Google AI Studio |
| `TELEGRAM_TOKEN` | Token từ BotFather |
| `TELEGRAM_CHAT_ID` | Chat ID của channel/group |

### 2. Chạy thử local
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q          # không cần mạng
python src/main.py           # cần TELEGRAM_* để gửi tin
```

### 3. Chạy lại thủ công
```bash
python src/main.py --symbols VNINDEX,VN30      # chỉ vài mã
python src/main.py --force-full                # tải lại toàn bộ lịch sử
python src/repair_data.py --dry-run            # xem CSV nào lệch chuẩn
python src/check_freshness.py                  # dữ liệu có cũ quá không
```

Workflow có input tương ứng (`force_full`, `symbols`) để chạy từ tab Actions.

### 4. Trigger từ cron-job.org (khuyến nghị)
- **URL**: `https://api.github.com/repos/FTU-kudo/VN-sector-analysis/actions/workflows/VN_Sector_Indices_Bot.yml/dispatches`
- **Method**: POST · **Headers**: `Authorization: Bearer <PAT>`, `Accept: application/vnd.github.v3+json`
- **Body**: `{"ref":"main"}`
- **Schedule**: Thứ 2–6, 17:15 (GMT+7)

`schedule:` trong workflow đang tắt để tránh gửi 2 tin/ngày; nếu cron-job.org hỏng hoàn toàn thì bật lại.

## Mẫu tin nhắn Telegram

```
📊 BÁO CÁO THỊ TRƯỜNG — 09/11/2026

📈 Chỉ số thị trường chung
🔴 VNINDEX 1,714.32 (-0.64%) | RSI: Trung tính (42.93) | MACD: Death 💀 | ADX: Sideways | Ichi: Tiêu cực
...

━━━━━━━━━━━━━━━━━
🤖 Phân tích AI
[Phân tích tự động từ Gemini]
```

Nếu dữ liệu mới nhất không phải phiên gần đây, tin nhắn mở đầu bằng dòng cảnh báo `⚠️ Dữ liệu mới nhất là phiên …`,
nên không bao giờ có chuyện báo cáo cũ mà trông như mới.
