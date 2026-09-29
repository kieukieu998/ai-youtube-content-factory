---
trigger: always_on
description: Các quy tắc cốt lõi không thể thương lượng (tối ưu token).
---

# Core Workflow Rules

Before marking any task as complete or making technical decisions, you **MUST**:
1. **Critical Thinking:** Phân tích edge cases và trade-offs trước khi code. Không tuân thủ mù quáng.
2. **Coding Standards:** Tuân thủ Python 3.10+ FastAPI, dùng Pydantic v2 và `get_db()` context manager.
3. **Safety First:** Media sources phải hợp lệ bản quyền. Luôn lắng nghe cờ Emergency STOP.
4. **Testing & Review:** Bắt buộc chạy tests và gọi Subagent Reviewer để kiểm duyệt trước khi hoàn thành task.

*(Để xem hướng dẫn chi tiết từng phần, hãy gọi các skill: `critical_thinking`, `coding_standards`, `copyright_safety`, `code_review`).*
