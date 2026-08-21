# Database Schema Design (SQLAlchemy & SQLite)

Thiết kế cơ sở dữ liệu cho hệ thống **AI Movie Content Factory**. Sử dụng kiểu dữ liệu chuẩn của SQLAlchemy để tương thích hoàn toàn khi chuyển đổi từ SQLite sang PostgreSQL.

---

## 1. Danh Sách Các Bảng (Entity Relationship)

```
[settings] (Cấu hình hệ thống, AI Provider, Daily Budget Limit, Telegram Alert)
     │
[movies] (Thông tin phim)
     ├──< [movie_sources] (Nguồn video & bản quyền)
     └──< [scripts] (Kịch bản review)
             └──< [episodes] (Từng tập video trong kịch bản)
                     ├──< [media_files] (File tạm: audio, sub, cuts, bgm)
                     ├──< [videos] (File video hoàn thiện 9:16)
                     │       └──< [publishes] (Lịch sử đăng TikTok)
                     │               └──< [analytics] (Chỉ số view, like, share)
                     └──< [jobs] (Hàng đợi xử lý tác vụ)

[ai_runs] (Lưu vết chi phí & token gọi LLM)
```

---

## 2. Chi Tiết Các Bảng

### 2.1. `settings` (Cấu hình toàn cục)
- `id` (INTEGER, PK, Auto-increment)
- `key` (VARCHAR(100), Unique, Not Null) - Ví dụ: `default_ai_provider`, `daily_budget_limit_usd`, `telegram_bot_token`, `operation_mode` (`full_auto` | `semi_auto`)
- `value` (TEXT, Not Null) - JSON hoặc chuỗi cấu hình
- `updated_at` (DATETIME, Default: CURRENT_TIMESTAMP)

### 2.2. `movies` (Danh mục phim)
- `id` (INTEGER, PK, Auto-increment)
- `title` (VARCHAR(255), Not Null)
- `original_title` (VARCHAR(255))
- `release_year` (INTEGER)
- `genre` (VARCHAR(100)) - Danh sách thể loại
- `duration_minutes` (INTEGER)
- `synopsis` (TEXT) - Tóm tắt nội dung
- `poster_url` (VARCHAR(500))
- `potential_score` (FLOAT) - Điểm tiềm năng do Movie Hunter chấm (0 - 100)
- `status` (VARCHAR(50), Default: 'discovered') - `discovered`, `analyzed`, `scripted`, `completed`
- `created_at` (DATETIME, Default: CURRENT_TIMESTAMP)

### 2.3. `movie_sources` (Nguồn media & bản quyền)
- `id` (INTEGER, PK, Auto-increment)
- `movie_id` (INTEGER, FK -> movies.id)
- `source_type` (VARCHAR(50)) - `user_upload`, `public_domain`, `licensed_partner`
- `file_path` (VARCHAR(500), Not Null) - Đường dẫn file gốc trong `media/source/`
- `license_info` (TEXT) - Thông tin giấy phép bản quyền
- `is_verified` (BOOLEAN, Default: False)
- `created_at` (DATETIME, Default: CURRENT_TIMESTAMP)

### 2.4. `scripts` (Kịch bản phim tổng thể)
- `id` (INTEGER, PK, Auto-increment)
- `movie_id` (INTEGER, FK -> movies.id)
- `title` (VARCHAR(255), Not Null)
- `target_episodes` (INTEGER, Default: 3)
- `full_script` (TEXT) - Nội dung kịch bản hoàn chỉnh
- `style` (VARCHAR(50)) - `dramatic`, `humorous`, `fast_paced`, `suspense`
- `language` (VARCHAR(10), Default: 'vi')
- `created_at` (DATETIME, Default: CURRENT_TIMESTAMP)

### 2.5. `episodes` (Từng tập video)
- `id` (INTEGER, PK, Auto-increment)
- `script_id` (INTEGER, FK -> scripts.id)
- `episode_number` (INTEGER, Not Null)
- `hook_text` (TEXT, Not Null) - Câu mở đầu 1-3s
- `hook_score` (FLOAT) - Điểm chất lượng của hook
- `content_text` (TEXT, Not Null) - Nội dung chi tiết của tập
- `call_to_action` (TEXT) - Câu kêu gọi xem tập tiếp/follow
- `status` (VARCHAR(50), Default: 'draft') - `draft`, `approval_pending`, `approved`, `voice_ready`, `rendered`, `qa_passed`, `published`
- `created_at` (DATETIME, Default: CURRENT_TIMESTAMP)

### 2.6. `media_files` (Quản lý file âm thanh, phụ đề và clip cắt)
- `id` (INTEGER, PK, Auto-increment)
- `episode_id` (INTEGER, FK -> episodes.id, Nullable=True)
- `file_type` (VARCHAR(50)) - `audio_tts`, `audio_bgm`, `subtitle_ass`, `subtitle_srt`, `cut_scene`, `preview`
- `file_path` (VARCHAR(500), Not Null)
- `duration_seconds` (FLOAT)
- `file_size_bytes` (BIGINT)
- `created_at` (DATETIME, Default: CURRENT_TIMESTAMP)

### 2.7. `videos` (Video hoàn thiện 9:16)
- `id` (INTEGER, PK, Auto-increment)
- `episode_id` (INTEGER, FK -> episodes.id)
- `file_path` (VARCHAR(500), Not Null) - Lưu trong `media/output/`
- `resolution` (VARCHAR(20), Default: '1080x1920')
- `fps` (INTEGER, Default: 30)
- `duration_seconds` (FLOAT, Not Null)
- `file_size_bytes` (BIGINT)
- `qa_status` (VARCHAR(50), Default: 'pending') - `pending`, `passed`, `failed`
- `qa_notes` (TEXT)
- `created_at` (DATETIME, Default: CURRENT_TIMESTAMP)

### 2.8. `jobs` (Quản lý hàng đợi tác vụ)
- `id` (INTEGER, PK, Auto-increment)
- `job_type` (VARCHAR(50), Not Null) - `MovieJob`, `ScriptJob`, `SceneSliceJob`, `VoiceJob`, `SubtitleJob`, `VideoJob`, `QAJob`, `PublishJob`, `CleanupJob`
- `status` (VARCHAR(50), Default: 'pending') - `pending`, `processing`, `completed`, `failed`, `cancelled`
- `progress` (INTEGER, Default: 0) - 0 đến 100%
- `payload` (TEXT) - Dữ liệu đầu vào dạng JSON
- `result` (TEXT) - Dữ liệu kết quả dạng JSON
- `error_message` (TEXT)
- `retry_count` (INTEGER, Default: 0)
- `max_retries` (INTEGER, Default: 3)
- `created_at` (DATETIME, Default: CURRENT_TIMESTAMP)
- `updated_at` (DATETIME, Default: CURRENT_TIMESTAMP)

### 2.9. `publishes` (Lịch sử đăng TikTok)
- `id` (INTEGER, PK, Auto-increment)
- `video_id` (INTEGER, FK -> videos.id)
- `platform` (VARCHAR(50), Default: 'tiktok')
- `title` (VARCHAR(255))
- `description` (TEXT)
- `hashtags` (TEXT)
- `tiktok_post_id` (VARCHAR(100))
- `published_at` (DATETIME)
- `status` (VARCHAR(50)) - `scheduled`, `publishing`, `published`, `failed`
- `error_message` (TEXT)

### 2.10. `analytics` (Số liệu đo lường hiệu suất)
- `id` (INTEGER, PK, Auto-increment)
- `publish_id` (INTEGER, FK -> publishes.id)
- `views_count` (INTEGER, Default: 0)
- `likes_count` (INTEGER, Default: 0)
- `comments_count` (INTEGER, Default: 0)
- `shares_count` (INTEGER, Default: 0)
- `avg_watch_time` (FLOAT, Default: 0.0)
- `retention_rate` (FLOAT, Default: 0.0)
- `recorded_at` (DATETIME, Default: CURRENT_TIMESTAMP)

### 2.11. `ai_runs` (Log tiêu thụ token & chi phí AI)
- `id` (INTEGER, PK, Auto-increment)
- `agent_name` (VARCHAR(100), Not Null)
- `provider` (VARCHAR(50), Not Null) - `gemini_free`, `gemini_paid`, `openai`, `claude`
- `model_name` (VARCHAR(100), Not Null)
- `prompt_tokens` (INTEGER, Default: 0)
- `completion_tokens` (INTEGER, Default: 0)
- `total_cost_usd` (FLOAT, Default: 0.0)
- `execution_time_ms` (INTEGER)
- `created_at` (DATETIME, Default: CURRENT_TIMESTAMP)
