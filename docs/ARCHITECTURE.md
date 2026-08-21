# System Architecture & Design

## 1. Tổng Quan Kiến Trúc
Hệ thống **AI Movie Content Factory** được xây dựng theo mô hình **Modular Monolith** kết hợp **Local Queue Worker**. Toàn bộ hệ thống có thể chạy hoàn toàn độc lập trên máy local trước khi mở rộng lên máy chủ Cloud / VPS.

```
                    ┌────────────────────────────────────────────────────────┐
                    │                      WEB BROWSER                       │
                    │      (Jinja2 Templates + DaisyUI + jQuery + Lucide)    │
                    └───────────────────────────┬────────────────────────────┘
                                                │ HTTP / REST / Server-Sent Events
                                                ▼
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    FASTAPI BACKEND CORE                                    │
│                                                                                            │
│  ┌───────────────────────┐  ┌──────────────────────────────┐  ┌─────────────────────────┐  │
│  │   Web UI & API Router │  │     Job Queue Dispatcher     │  │   AI Provider Router    │  │
│  │  - Semi/Auto Modes    │  │    - SQLite Job Poller       │  │   - Gemini (Free Mặc định)│  │
│  │  - Approval Gate UI   │  │    - Background Task Worker  │  │   - DeepSeek / OpenAI   │  │
│  └───────────┬───────────┘  └──────────────┬───────────────┘  └────────────┬────────────┘  │
│              │                             │                               │               │
│              ▼                             ▼                               ▼               │
│  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                                11 MODULAR AI AGENTS                                  │  │
│  │   [Hunter] ──► [Analyst] ──► [Script] ──► [Hook] ──► [Scene Slicer (PySceneDetect)]  │  │
│  │                                                                 │                    │  │
│  │   [Publishing] ◄── [SEO] ◄── [QA] ◄── [Editor (FFmpeg+BGM)] ◄── [Voice + Kinetic Sub]│  │
│  └─────────────────────────────────────────┬────────────────────────────────────────────┘  │
│                                            │                                               │
│  ┌─────────────────────────────────────────┴────────────────────────────────────────────┐  │
│  │                     SYSTEM UTILITIES & SAFETY SERVICES                               │  │
│  │   - Storage Auto Cleanup (media/working/)       - Emergency STOP ALL Controller      │  │
│  │   - Token & Daily Budget Guard                  - Telegram / Email Alert Bot         │  │
│  └──────────────────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────┬───────────────────────────────────────────────┘
                                             │
                       ┌─────────────────────┴─────────────────────┐
                       ▼                                           ▼
          ┌─────────────────────────┐                 ┌─────────────────────────┐
          │     SQLITE DATABASE     │                 │   LOCAL MEDIA STORAGE   │
          │  - movie_ai.db          │                 │  - media/source/        │
          │  - metadata, logs, jobs │                 │  - media/bgm/ (Nhạc nền)│
          │  - scripts & settings   │                 │  - media/working/ (Tạm) │
          │  - ai_runs & budget     │                 │  - media/output/ (9:16) │
          └─────────────────────────┘                 └─────────────────────────┘
```

---

## 2. Các Chế Độ Vận Hành (Operating Modes)
1. **Full-Auto Mode (Tự động 100%):**
   - Hệ thống tự động chạy toàn bộ pipeline từ cào phim, phân tích, viết kịch bản, cắt cảnh, sinh voice, ghép nhạc nền (BGM), tạo phụ đề động, render video 9:16 đến xuất bản lên TikTok theo lịch trình.
2. **Semi-Auto Mode (Duyệt có kiểm soát - Human-in-the-loop):**
   - Dừng lại tại **Approval Gate** sau khi sinh kịch bản & 3-5 Hooks.
   - Người dùng có thể nghe thử giọng đọc, chỉnh sửa câu thoại, chọn Hook ưng ý nhất trước khi kích hoạt lệnh Render và Publish.

---

## 3. Hệ Thống Xử Lý Video & Âm Thanh Nâng Cao
- **Smart Scene Slicing:** Sử dụng `PySceneDetect` bóc tách video gốc thành các đoạn clip nhỏ (2 - 5 giây) để tránh cảnh quay dài gây nhàm chán trên TikTok.
- **Audio Ducking & BGM:** Tự động hòa trộn nhạc nền không bản quyền với giọng đọc AI (tự động giảm âm lượng BGM xuống 15-20% khi có giọng đọc và tăng lên khi nghỉ).
- **Kinetic Subtitles:** Tạo phụ đề động chuẩn ASS (Advanced SubStation Alpha) với hiệu ứng đổi màu theo từng từ được đọc (Word-by-word highlight).
- **Anti-Shadowban Filter:** Tự động lật khung hình nhẹ, điều chỉnh tốc độ 1.02x, dynamic zoom và chèn watermark kênh.

---

## 4. Quản Lý Tài Nguyên & Van An Toàn (Safety Guards)
1. **Van Ngân Sách AI (Daily Budget Guard):**
   - Cho phép đặt mức trần chi phí mỗi ngày (ví dụ: $0 đối với gói Gemini Free, hoặc tối đa $2/ngày khi dùng OpenAI/Claude).
   - Tự động ngắt gọi API khi vượt ngưỡng và cảnh báo về Dashboard / Telegram.
2. **Tự Động Dọn Rác Ổ Cứng (Storage Auto Cleanup):**
   - Xóa ngay các file cắt tạm trong `media/working/` sau khi render hoàn tất.
   - Lưu trữ có thời hạn đối với `media/output/` (tự động dọn dẹp sau 15-30 ngày).
3. **Nút Dừng Khẩn Cấp (Emergency STOP ALL):**
   - Lập tức hủy bỏ toàn bộ Job đang chờ và ngắt các tiến trình FFmpeg / Network requests đang thực thi.
