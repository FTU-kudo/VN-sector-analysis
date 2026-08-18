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
