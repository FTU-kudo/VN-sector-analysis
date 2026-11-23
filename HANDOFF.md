<!-- HANDOFF.md -->
# NHẬT KÝ BẢO TRÌ & XỬ LÝ LỖI (HANDOFF LOG)
**Dự án:** VN-sector-analysis (Bot Telegram phân tích chỉ số ngành)
**Thời gian xử lý:** Đêm ngày 18/08/2026 - Rạng sáng ngày 19/08/2026

---

## 📅 [18/08/2026 23:30] Khắc phục lỗi Cache của GitHub Actions
- **Tình trạng:** Bot Telegram chỉ gửi tin nhắn với dữ liệu của ngày 03/08/2026 mặc dù GitHub Actions vẫn chạy hàng ngày.
- **Nguyên nhân:** Lỗi cơ chế khôi phục cache của GitHub Actions. Khi script gặp lỗi (API không lấy được dữ liệu), nó sẽ lấy lại bộ đệm cũ (`df_old`) từ ngày 03/08, sau đó GitHub Actions lưu đè bộ đệm lỗi này lên khiến vòng lặp cache cũ bị lặp lại liên tục.
- **Giải pháp:** 
  - Khóa phiên bản `vnstock==4.0.2` trong `requirements.txt` để đảm bảo tương thích ổn định cho tài khoản miễn phí.
  - Sửa file `.github/workflows/VN_Sector_Indices_Bot.yml` để cấp quyền `contents: write`.
  - Thiết lập cơ chế tự động commit cache mới (`data/*.csv`) đẩy thẳng lên nhánh `main` để tránh phụ thuộc vào Actions Cache có thể bị kẹt.

## 📅 [18/08/2026 23:55] Sửa lỗi Nguồn dữ liệu Vietcap (VCI) thay đổi mã nội bộ
- **Tình trạng:** Dù đã sửa cache, code vẫn thất bại và phải dùng lại cache. Thử chuyển qua nguồn `KBS` nhưng nguồn này không hỗ trợ các chỉ số ngành phụ trợ như VNMID, VNSML, VNFIN...
- **Nguyên nhân:** Khám phá ra rằng API của máy chủ Vietcap (VCI) vừa mới thay đổi cấu trúc mã nội bộ (Symbol Names). Họ đổi `VNMID` thành `VNMIDCAP`, `VNSML` thành `VNSMALLCAP`, và `VNALL` thành `VNALLSHARE`. Trong khi đó thư viện `vnstock 4.0.2` vẫn "hard-code" các tên cũ, dẫn tới API trả về chuỗi rỗng và gây ra lỗi `ValueError: Không tìm thấy dữ liệu`.
- **Giải pháp:** 
  - Áp dụng kỹ thuật **Monkey Patching** ngay ở đầu file `01_fetch.py`.
  - Thay đổi ánh xạ (mapping) của thư viện `vnstock` ngay trên RAM trước khi gọi `Quote()` để sửa ép tên thành mã mới của VCI.

## 📅 [19/08/2026 00:08] Bỏ qua lỗi bắt buộc thư viện vẽ biểu đồ trên Ubuntu
- **Tình trạng:** Sau khi Monkey Patch VCI, GitHub Actions báo lỗi `ImportError: No charting library available`.
- **Nguyên nhân:** Việc Import cấu hình VCI khiến `vnstock` tải toàn bộ module và nó bắt buộc phải có thư viện `vnstock_ezchart`. Mặc dù đã thêm thư viện này vào `requirements.txt`, máy ảo Ubuntu của GitHub vẫn báo thiếu thư viện do nó là bản Linux tối giản, không có sẵn các thư viện đồ họa hệ thống (libgl, tkinter) mà `matplotlib` cần.
- **Giải pháp:** 
  - Viết một đoạn code giả lập module (Module Mocking).
  - Khởi tạo thư viện ảo `sys.modules['vnstock.common.viz']` với biến `HAS_VNSTOCK_EZCHART = True` để "đánh lừa" `vnstock`, giúp bot vượt qua bước kiểm tra này một cách mượt mà mà không phải tốn thời gian tải các thư viện đồ họa không cần thiết.

## 📅 [19/08/2026 00:15] Khắc phục lỗi Timeout của Gemini API
- **Tình trạng:** Dữ liệu thị trường lấy thành công, bot chuẩn bị gửi tin nhắn nhưng lỗi `Read timed out (30s)` ở phần sinh báo cáo AI bằng thư viện `requests`.
- **Nguyên nhân:** Máy chủ Gemini API bản miễn phí thỉnh thoảng phản hồi chậm trong những giờ cao điểm dẫn đến quá thời gian đợi mặc định của code cũ.
- **Giải pháp:** 
  - Sửa đổi file `03_analysis.py`.
  - Nâng thời gian timeout từ 30 giây lên 60 giây.
  - Bổ sung cơ chế **Retry** (gọi lại API tự động tối đa 3 lần). Nếu lần 1 thất bại, bot sẽ thử gửi lại để tránh sập hệ thống.

---
**Trạng thái hiện tại:** Dự án đã hoạt động ổn định trở lại, dữ liệu cache từ Vietcap đã lưu chính xác ngày gần nhất, bot đã gửi tin với phân tích của AI bình thường trên kênh Telegram. Mọi thay đổi đều đã được push lên `main`.

---

## 📅 [23/11/2026] Chuyển hẳn nguồn dữ liệu: bỏ vnstock, dùng API đã mua

- **Tình trạng:** Bot chạy tốt đến hết 09/11/2026 rồi chết. Từ 10/11 đến 20/11 có **10 lần chạy liên tiếp đều đỏ**, tất cả
  dừng ở bước `Install dependencies`, nên pipeline không chạy và dữ liệu đứng yên ở phiên **09/11/2026** (VNINDEX 1.714,32).
  Không có cảnh báo nào được gửi đi, nên sự cố chỉ lộ ra khi kiểm tra tay.
- **Nguyên nhân:** `vnstock` và `vnai` **không có trên PyPI**; cả hai chỉ phân phối qua extra index
  `https://vnstocks.com/api/simple` khai báo ở dòng đầu `requirements.txt`. Khi index đó không còn phản hồi, `pip install`
  thất bại trước khi chạy được một dòng code nào. `requirements.txt` không thay đổi từ 30/09, nên đây là phía nguồn hỏng,
  không phải phía repo. (Ghi chú cũ "khoá `vnstock==4.0.2`" ở trên đã bị thay bằng `vnstock>=4.0.8` từ 30/09 và nay không còn
  hiệu lực: gói đã bị xoá khỏi dự án.)
- **Giải pháp:**
  - Xoá toàn bộ `vnstock`, `vnai`, `vnstock_ezchart`, monkey patch `_VCI_INDEX_MAPPING` và mẹo `sys.modules['vnstock.common.viz']`.
  - Thêm `src/yuanta_client.py`: client cho hai endpoint công khai của nguồn đã mua (nến ngày `tradingview/history` và bảng chỉ số
    `list_index`), có session giữ cookie, tự đi theo bước nhảy chống bot `?jskey=` (chỉ cùng host, tối đa 3 lần), retry có
    backoff, và đọc `t` theo UTC (không theo giờ máy).
  - `requirements.txt` giờ chỉ còn `pandas`, `numpy`, `requests` — cài được từ PyPI thuần, không cần extra index.
  - Bỏ bước `actions/cache` cho `data/`: CSV đã nằm trong git, cache chỉ có thể khôi phục bản cũ hơn đè lên bản mới checkout —
    đúng cơ chế đã gây ra sự cố 18/08.
  - Thêm `concurrency` để hai lần chạy không tranh nhau commit; bỏ `|| true` ở bước push để lỗi push không bị nuốt.
  - Thêm cảnh báo Telegram khi workflow lỗi (`src/notify_failure.py`, chỉ dùng stdlib nên vẫn chạy được khi `pip install` hỏng),
    và cảnh báo trong chính tin nhắn báo cáo khi dữ liệu đã cũ.
  - Thêm `src/check_freshness.py` (fail khi dữ liệu cũ quá 8 ngày giao dịch — Tết khoảng 6 ngày nên vẫn qua) và
    `src/data_quality.py` + `data/quality_report.json` để mọi sửa đổi dữ liệu đều được ghi lại.
  - Thêm 57 test (`tests/`) chạy không cần mạng, và workflow chạy `pytest` trước pipeline.
- **Dữ liệu đã sửa một lần bằng `src/repair_data.py`:**
  - Xoá nến ma Thứ Bảy **2008-08-16** trong VNINDEX (close 900,26 nằm giữa 488,94 và 511,53) — nến này làm sai mọi chỉ báo cuộn.
  - 17 nến VNINDEX có `close` nằm ngoài `[low, high]`: nới `low`/`high` cho bao được `close` (giữ nguyên chuỗi close).
  - Khoảng 400 nến (chủ yếu chỉ số ngành 2018–2019) có `open` bị giữ nguyên từ phiên trước nhiều ngày liền: kéo `open` về trong
    khoảng `[low, high]` thay vì thổi phồng `high`/`low` bằng giá trị cũ.
- **Chưa kiểm chứng được:** sandbox không kết nối được tới host dữ liệu, nên hành vi endpoint vẫn dựa trên mô tả/hình ảnh.
  Lần chạy thật đầu tiên cần xem log: số nến tải về mỗi chỉ số, `data/quality_report.json` (nhất là `board_check`), và mã VNUTI
  mới thêm. Nếu nguồn không có VNUTI thì chỉ cần xoá một dòng trong `INDICES`.
