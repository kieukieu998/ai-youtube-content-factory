# Copyright Safety & Emergency Control Rules

## 1. Nguyên Tắc An Toàn Bản Quyền & Nguồn Media
- **Kiểm Soát Nguồn Media:**
  - Hệ thống **chỉ** sử dụng các nguồn media (video, trailer, audio) do người dùng cung cấp trực tiếp, nguồn đã mua bản quyền hoặc nguồn được cấp phép công khai (Creative Commons / Public Domain).
  - Không tự ý bypass DRM, vượt qua rào cản thanh toán hoặc cào nội dung từ các nền tảng có biện pháp bảo vệ bản quyền nghiêm ngặt.
- **Lưu Vết Nguồn Gốc (Provenance Tracking):**
  - Mọi bản ghi trong bảng `movie_sources` và `media_files` bắt buộc phải lưu thông tin: `source_url`, `license_type`, `attribution_info` và `verified_status`.

---

## 2. Quy Trình Kiểm Định QA Trước Xuất Bản (QA Gate)
- Một video **chỉ được phép chuyển sang trạng thái sẵn sàng xuất bản (Ready to Publish)** khi và chỉ khi:
  1. `QA Agent` trả về kết quả `passed = True`.
  2. Thời lượng (Duration) nằm trong giới hạn cho phép (ví dụ: 60s - 180s).
  3. Video có đầy đủ luồng Video (1080x1920, >25fps) và Audio (Stereo, âm lượng chuẩn hóa không bị rè/vỡ tiếng).
  4. Trạng thái bản quyền của media source được xác nhận là hợp lệ.

---

## 3. Cơ Chế Nút Dừng Khẩn Cấp (Emergency STOP ALL)
- Hệ thống bắt buộc phải có cờ trạng thái khẩn cấp toàn cục (`SYSTEM_EMERGENCY_STOP`).
- Khi người dùng bấm **STOP ALL**:
  1. Đổi ngay cờ hệ thống sang trạng thái `STOPPED`.
  2. Lập tức hủy bỏ các job đang ở trạng thái `pending`.
  3. Gửi tín hiệu ngắt (SIGTERM / terminate process) tới các tiến trình FFmpeg hoặc sub-worker đang chạy.
  4. Cập nhật trạng thái các job đang chạy sang `cancelled`.
  5. Khóa tính năng tự động publish lên TikTok cho đến khi người dùng chủ động mở khóa.
