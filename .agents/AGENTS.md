# AGENTS.md — AI Movie Content Factory

## 1. Mục Tiêu Dự Án
Xây dựng hệ thống AI tự động tìm kiếm phim, phân tích nội dung, tạo kịch bản review ngắn, chia thành nhiều video, tạo voice/subtitle, render video dọc (9:16) và hỗ trợ xuất bản lên TikTok.

Hệ thống được thiết kế theo nguyên tắc: **Local First → Modular → Queue-based → Cloud Ready**.

---

## 2. Công Nghệ Bắt Buộc (Tech Stack)
- **Backend:** Python 3.10+ & FastAPI
- **Template Engine:** Jinja2 (Server-side rendering)
- **Frontend Core:** HTML5, CSS3, JavaScript / jQuery
- **UI Framework:** Tailwind CSS + DaisyUI
- **Icons & UI Extras:** Lucide Icons, SweetAlert2 (Notification/Dialog), DataTables (Bảng dữ liệu), Chart.js (Biểu đồ)
- **Database & ORM:** SQLite (giai đoạn Local) + SQLAlchemy 2.0 (chuẩn bị sẵn sàng migrate sang PostgreSQL)
- **Data Validation:** Pydantic v2
- **Audio Engine (TTS):** Provider độc lập (Mặc định: `edge-tts` miễn phí 100%, mở rộng: OpenAI TTS / ElevenLabs)
- **Subtitle Engine:** SRT/ASS Kinetic Generator kết hợp timestamp từ `edge-tts` hoặc `faster-whisper`
- **Video Engine:** FFmpeg (định dạng dọc 9:16, 1080x1920) + `PySceneDetect`
- **AI Providers:** Interface trừu tượng độc lập (Mặc định: **Google Gemini Free Tier**, mở rộng sẵn sàng: **DeepSeek**, **OpenAI**, **Anthropic Claude**)

---

## 3. Nguyên Tắc Kiến Trúc
1. **Không dùng Laravel** cho core backend.
2. **Không dùng MySQL/PostgreSQL** trong giai đoạn MVP (dùng SQLite nhưng thiết kế schema chuẩn SQLAlchemy để migrate mượt mà).
3. **Không dùng SPA Framework (React/Vue)** trong MVP để tối ưu tốc độ phát triển và đơn giản hóa bảo trì.
4. **Không hard-code AI Provider/Model:** Toàn bộ Agent phải gọi qua lớp Base AI Provider Abstraction.
5. **Tách biệt Business Logic:** Tuyệt đối không viết logic xử lý nghiệp vụ bên trong route hoặc template.
6. **Module hóa cao (Modular):** Mỗi chức năng (Hunter, Script, Voice, Video, Publishing...) là một module độc lập trong `app/`.
7. **Xử lý bất đồng bộ (Queue-based):** Mọi tác vụ nặng (tải media, sinh voice, sinh sub, render video) phải chạy qua bảng `jobs` với background worker.
8. **Quản lý Media:** Không lưu file binary lớn vào database. Database chỉ lưu metadata, URL hoặc đường dẫn file tương đối.

---

## 4. Cấu Trúc Thư Mục Chuẩn (Project Layout)
```text
AI-Movie-Content-Factory/
├── .agents/                    # Cấu hình và quy tắc cho AI Agent
│   ├── AGENTS.md               # File này: Tổng quan kiến trúc & quy tắc
│   └── rules/                  # Các quy tắc chi tiết
│       ├── coding_standards.md # Chuẩn viết code, error handling & logging
│       └── copyright_safety.md # Quy định an toàn bản quyền & Media
├── app/                        # Mã nguồn ứng dụng FastAPI
│   ├── api/                    # API routes & Controller endpoints
│   ├── agents/                 # Logic của 11 AI Agents
│   ├── ai/                     # AI Provider Abstraction (Gemini, OpenAI, Claude)
│   ├── movies/                 # Module quản lý phim & metadata
│   ├── video/                  # Xử lý video & FFmpeg render
│   ├── audio/                  # Xử lý TTS & âm thanh
│   ├── subtitle/               # Xử lý phụ đề SRT & ASS
│   ├── publishing/             # TikTok API integration
│   ├── analytics/              # Phân tích hiệu suất video
│   ├── scheduler/              # Lập lịch tự động (Cron/APScheduler)
│   ├── database/               # Models, Sessions & Migrations
│   └── core/                   # Config, Security, Event handlers
├── templates/                  # Giao diện Jinja2 (HTML)
├── static/                     # Assets: css, js, images
│   ├── css/
│   ├── js/
│   └── images/
├── docs/                       # Tài liệu kỹ thuật chi tiết
│   ├── ARCHITECTURE.md         # Kiến trúc hệ thống & Queue
│   ├── DATABASE_SCHEMA.md      # Chi tiết các bảng database
│   ├── AGENTS_SPECIFICATION.md # Đặc tả chi tiết 11 Agent (Prompt, I/O)
│   └── FFMPEG_PRESETS.md       # Cấu hình bộ lọc FFmpeg 9:16
├── data/                       # Chứa SQLite database (movie_ai.db)
├── media/                      # Lưu trữ media theo vòng đời
│   ├── source/                 # Video/Audio gốc được cấp phép
│   ├── working/                # File tạm (audio cắt, chunks, srt)
│   ├── output/                 # Video hoàn thiện (9:16 1080x1920)
│   └── archive/                # Lưu trữ sau khi publish
├── logs/                       # System & Worker logs
├── tests/                      # Unit & Integration tests
├── config/                     # File cấu hình yaml/json
├── main.py                     # Entry point khởi chạy ứng dụng FastAPI
├── requirements.txt            # Danh sách thư viện Python
└── .env                        # Biến môi trường & API Keys
```

---

## 5. Danh Sách 11 AI Agents & Nhiệm Vụ

| Agent | Nhiệm Vụ Cốt Lõi | Output Chính |
| :--- | :--- | :--- |
| **1. Movie Hunter** | Tìm kiếm phim theo tiêu chí, thu thập metadata, lọc trùng và chấm điểm tiềm năng. | `MovieCandidate` |
| **2. Movie Analyst** | Phân tích cốt truyện, cao trào, twist, điểm nhấn và đề xuất số tập video. | `MovieAnalysis` |
| **3. Script Writer** | Viết kịch bản ngắn theo phong cách cấu hình, chia phân cảnh (scenes). | `ScriptData` |
| **4. Hook Generator** | Tạo 3-5 câu mở đầu (Hook) giật gân trong 1-3s đầu, chấm điểm và chọn câu tốt nhất. | `SelectedHook` |
| **5. Scene Selector** | Khớp từng đoạn kịch bản với đoạn video phù hợp từ kho media được cấp phép. | `TimelinePlan` |
| **6. Voice Agent** | Tạo giọng đọc AI (TTS) theo cấu hình giọng điệu, tốc độ và kiểm tra chất lượng file audio. | `AudioTrack` |
| **7. Subtitle Agent** | Tạo phụ đề SRT/ASS đồng bộ chính xác với audio, style chữ tối ưu cho mobile. | `SubtitleFile` |
| **8. Video Editor** | Gọi FFmpeg render video dọc 9:16 (1080x1920), mix audio, ghép subtitle và hiệu ứng. | `RenderedVideo` |
| **9. QA Agent** | Kiểm tra chất lượng video trước khi đăng (thời lượng, bitrate, âm thanh, khung đen). | `QAResult (Pass/Fail)` |
| **10. SEO Agent** | Sinh tiêu đề hấp dẫn, mô tả ngắn, hashtag trending phù hợp nội dung phim. | `SEOMetadata` |
| **11. Analytics Agent**| Đánh giá số liệu tương tác (view, like, retention) để tối ưu hóa kịch bản và hook cho các đợt sau. | `PerformanceReport` |

---

## 6. Pipeline Xử Lý
```text
Scheduler (Lập lịch)
   │
   ▼
[1] Movie Hunter ──► [2] Movie Analyst ──► [3] Script Writer & [4] Hook Generator
                                                       │
                                                       ▼
                                              [5] Scene Selector
                                                       │
                     ┌─────────────────────────────────┴─────────────────────────────────┐
                     ▼                                                                   ▼
             [6] Voice Agent                                                     [7] Subtitle Agent
                     │                                                                   │
                     └─────────────────────────────────┬─────────────────────────────────┘
                                                       │
                                                       ▼
                                              [8] Video Editor (FFmpeg)
                                                       │
                                                       ▼
                                              [9] QA Agent (Kiểm định)
                                                       │ (Đạt chuẩn)
                                                       ▼
                                              [10] SEO Agent (Title/Hashtag)
                                                       │
                                                       ▼
                                              Publishing Module (TikTok API)
                                                       │
                                                       ▼
                                              [11] Analytics Agent ──► Phản hồi tối ưu hóa
```

---

## 7. Quy Tắc Dành Cho AI Coding Assistant (Antigravity)
1. **Đọc kỹ tài liệu trước khi sửa code:** Kiểm tra file quy tắc tương ứng trong `.agents/rules/` và `docs/`.
2. **Không tự ý thay đổi Tech Stack:** Bắt buộc tuân thủ FastAPI, Jinja2, Tailwind/DaisyUI, SQLAlchemy.
3. **Error Handling chặt chẽ:** Tất cả các endpoint, worker job và module gọi AI/FFmpeg phải có try-catch, ghi log chi tiết và cập nhật trạng thái job (`failed` + `error_message`).
4. **Bảo mật tuyệt đối:** Không bao giờ hard-code API Key hay Secret Token trong mã nguồn. Mọi cấu hình nhạy cảm phải đọc từ file `.env`.
5. **Cơ chế Emergency STOP:** Luôn đảm bảo hệ thống có khả năng ngắt ngay lập tức mọi job đang chạy khi người dùng bấm nút Dừng khẩn cấp.
