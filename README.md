# AI Movie Content Factory

Hệ thống AI tự động hóa quy trình tìm kiếm phim, phân tích cốt truyện, tạo kịch bản review ngắn, chia tập, lồng tiếng AI (TTS), tạo phụ đề, render video chuẩn TikTok (9:16) và hỗ trợ xuất bản tự động.

---

## 🚀 Triết Lý & Kiến Trúc
- **Local First:** Chạy mượt mà trên máy tính cá nhân (SQLite, FastAPI, Local Workers, FFmpeg).
- **Modular:** 11 AI Agents độc lập, dễ dàng thay thế hoặc nâng cấp từng module.
- **Queue-based:** Xử lý các tác vụ render/AI bất đồng bộ, không nghẽn hệ thống.
- **Cloud Ready:** Sẵn sàng chuyển đổi sang PostgreSQL, S3/R2 và phân tán nhiều worker.

---

## 🛠️ Công Nghệ Sử Dụng
- **Backend:** Python 3.10+, FastAPI, SQLAlchemy 2.0, Pydantic v2
- **Frontend:** Jinja2 Templates, Tailwind CSS, DaisyUI, jQuery, Lucide Icons, DataTables, Chart.js, SweetAlert2
- **Audio & Video:** `edge-tts` (Local TTS), FFmpeg (Filter Graph 9:16)
- **AI Engine:** Hỗ trợ OpenAI, Google Gemini, Anthropic Claude qua Provider Abstraction

---

## 📁 Cấu Trúc Dự Án
```text
AI-Movie-Content-Factory/
├── .agents/                    # Bộ quy tắc & chỉ dẫn cho AI Coding Assistant
│   ├── AGENTS.md               # Kiến trúc & quy chuẩn cốt lõi
│   └── rules/                  # Quy tắc code & bản quyền
├── docs/                       # Tài liệu kỹ thuật chi tiết
│   ├── ARCHITECTURE.md         # Kiến trúc hệ thống & Queue
│   ├── DATABASE_SCHEMA.md      # Chi tiết các bảng Database
│   ├── AGENTS_SPECIFICATION.md # Đặc tả 11 AI Agents
│   └── FFMPEG_PRESETS.md       # Chuỗi bộ lọc FFmpeg 9:16
├── app/                        # Mã nguồn ứng dụng FastAPI
├── templates/                  # Giao diện web Jinja2
├── static/                     # CSS, JS, Images
├── data/                       # Chứa SQLite database
├── media/                      # Lưu trữ source, working & output video
└── main.py                     # File chạy chính
```

---

## 📖 Tài Liệu Tham Khảo Chi Tiết
- [Kiến Trúc & Queue System](docs/ARCHITECTURE.md)
- [Thiết Kế Database Schema](docs/DATABASE_SCHEMA.md)
- [Đặc Tả 11 AI Agents](docs/AGENTS_SPECIFICATION.md)
- [Cấu Hình FFmpeg Render 9:16](docs/FFMPEG_PRESETS.md)
- [Quy Tắc Viết Code](.agents/rules/coding_standards.md)
- [Quy Định An Toàn Bản Quyền](.agents/rules/copyright_safety.md)
