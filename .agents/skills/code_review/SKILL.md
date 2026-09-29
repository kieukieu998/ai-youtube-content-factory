---
name: code_review
description: Tiêu chuẩn tự động Code Review sau mỗi task.
---

# Code Review & Quality Assurance Rules

## 1. Tự Động Code Review Sau Mỗi Task (Automatic Subagent Review)
- **Quy trình bắt buộc:** Sau khi hoàn thành việc viết mã hoặc thay đổi logic cho bất kỳ task nào, AI Assistant phải tự động kích hoạt subagent `code_reviewer` (hoặc thực hiện quy trình review độc lập) để đánh giá code trước khi bàn giao cho người dùng.
- **Tiêu chí đánh giá:**
  1. **Logic & Edge cases:** Phát hiện null pointer, race conditions, boundary bugs, xử lý thiếu trường hợp.
  2. **Bảo mật (Security):** Kiểm tra injection, lộ key/token, rò rỉ tài nguyên (file handles, database sessions).
  3. **Hiệu năng & Khả năng mở rộng:** Tối ưu truy vấn database, tránh blocking operations trên FastAPI async loop, tối ưu FFmpeg subprocess.
  4. **Clean Code & Tuân thủ chuẩn:** Đảm bảo type hints, Pydantic validation, cấu trúc thư mục chuẩn và xử lý ngoại lệ đầy đủ.

---

## 2. Định dạng báo cáo Review (Review Output Format)
Báo cáo kết quả review gửi cho người dùng phải luôn có cấu trúc rõ ràng:
- 🚨 **Lỗi nghiêm trọng (Critical Bugs):** (nếu có)
- ⚠️ **Cảnh báo bảo mật & Hiệu năng (Warnings):** (nếu có)
- 💡 **Gợi ý tối ưu & Clean Code (Suggestions):** (nếu có)
- ✅ **Đánh giá tổng quan (Verdict):** `Approved` / `Changes Required`.
