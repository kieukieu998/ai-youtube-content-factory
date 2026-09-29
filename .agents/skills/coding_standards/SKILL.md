---
name: coding_standards
description: Chuẩn viết code Python, FastAPI, SQLAlchemy và xử lý lỗi.
---

# Coding Standards & Architecture Rules

## 1. Python & FastAPI Best Practices
- **Phiên bản Python:** Python 3.10 trở lên. Bắt buộc sử dụng Type Hinting đầy đủ (`typing`, `pydantic`).
- **Cấu trúc Route:**
  - Route chỉ làm nhiệm vụ nhận request, validate bằng Pydantic model, gọi service/agent tương ứng và trả response.
  - Không viết SQL query trực tiếp hoặc logic tính toán phức tạp bên trong route handler.
- **Dependency Injection:** Sử dụng `Depends` của FastAPI để inject database session (`get_db`), settings, và background queue runner.
- **Pydantic Validation:** Sử dụng Pydantic v2 để validate mọi input payload và serialize response schema (`response_model`).

---

## 2. Database & SQLAlchemy Rules
- **Session Lifecycle:** Mọi session database phải được quản lý qua context manager (`with get_db() as db:` hoặc FastAPI Depends) để đảm bảo session luôn được đóng/rollback khi có lỗi.
- **Tính tương thích Cross-DB:**
  - Dùng chuẩn SQLAlchemy 2.0 (`select()`, `execute()`, `scalars()`).
  - Không dùng các câu SQL string native đặc thù riêng cho SQLite (như `PRAGMA`) để sau này chuyển sang PostgreSQL không bị lỗi cú pháp.
- **Khóa ngoại & Index:** Mọi quan hệ giữa các bảng (`movie_id`, `script_id`, `job_id`) phải có Foreign Key ràng buộc và đánh Index cho các cột thường xuyên query/filter (status, created_at).

---

## 3. Quản Lý Lỗi & Logging
- **Logging có ngữ cảnh:** Sử dụng module `logging` chuẩn của Python hoặc `Loguru`. Ghi log rõ ràng kèm theo `job_id`, `movie_id` hoặc `step_name`.
  - Format log mẫu: `[2026-08-21 12:00:00] [INFO] [VideoJob #42] FFmpeg rendering started for Movie ID 10`.
- **Không Silent Catch:** Tuyệt đối không dùng `except Exception: pass`. Mọi exception phải được log lại và ném ra HTTP status code phù hợp hoặc cập nhật trạng thái `failed` cho Job.
- **Safe Subprocess (FFmpeg & Shell):**
  - Mọi lệnh gọi FFmpeg hoặc CLI tool ngoài phải dùng `subprocess.run` với danh sách arguments dạng mảng (tránh command injection), có timeout và bắt `stderr` khi có lỗi.

---

## 4. AI Provider Abstraction Rules
- **Base Interface:** Mọi provider (OpenAI, Gemini, Claude) phải kế thừa từ một abstract base class:
  ```python
  class BaseAIProvider(ABC):
      @abstractmethod
      async def generate_text(self, prompt: str, system_prompt: str = "") -> str:
          pass

      @abstractmethod
      async def generate_structured(self, prompt: str, schema: Type[BaseModel]) -> BaseModel:
          pass
  ```
- **Fallback & Retry:** Tích hợp cơ chế retry tự động (1-2 lần với exponential backoff) khi gặp lỗi Rate Limit hoặc Network timeout từ AI API.
