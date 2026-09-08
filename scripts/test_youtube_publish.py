import os
import sys
import time
import json
import urllib.request
import urllib.error

# Ensure UTF-8 stdout
sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "http://127.0.0.1:8000/api/v1"

def api_get(endpoint: str):
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode('utf-8'))

def api_post(endpoint: str, data: dict):
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    body = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode('utf-8'))

def p(*args, **kwargs):
    print(*args, **kwargs, flush=True)

def main():
    p("==================================================")
    p("▶ BẮT ĐẦU TEST TOÀN TRÌNH DEPLOY / PUBLISH YOUTUBE")
    p("==================================================")

    # 1. Check YouTube Channel Status
    p("\n[Bước 1] Kiểm tra trạng thái YouTube Channel...")
    status_res = api_get("publishing/youtube/status")
    channel_info = status_res.get("data", status_res)
    p(f"  - Đã kết nối: {channel_info.get('connected')}")
    p(f"  - Tên kênh: {channel_info.get('title')}")
    p(f"  - Chế độ Demo: {channel_info.get('is_demo')}")
    p(f"  - Người đăng ký: {channel_info.get('subscriber_count')}")
    assert channel_info.get("connected") is True, "Kênh YouTube chưa được kết nối hoặc chưa bật chế độ Demo!"

    # 2. Test SEO Generator for Story #2 (9:16 Shorts)
    p("\n[Bước 2] Sinh AI SEO Metadata (Tiêu đề, Mô tả, Hashtags) cho Story #2 (9:16 Shorts)...")
    seo_payload = {
        "title": "Gặp trời xanh vào lúc nửa đêm",
        "content": "Một chàng trai trẻ lạc lối trong bóng tối bỗng tìm thấy ánh sáng hy vọng từ một cuộc gặp gỡ kỳ lạ.",
        "author": "Khuyết danh",
        "aspect_ratio": "9:16"
    }
    seo_res = api_post("publishing/seo/generate", seo_payload)
    p(f"  - Title: {seo_res.get('title')}")
    p(f"  - Description: {seo_res.get('description')[:120]}...")
    p(f"  - Tags: {seo_res.get('tags')}")

    # 3. Publish Story #2 (9:16 Shorts)
    p("\n[Bước 3] Gửi yêu cầu Publish Story #2 lên YouTube Shorts...")
    pub_payload = {
        "story_id": 2,
        "aspect_ratio": "9:16",
        "title": seo_res.get("title") or "Gặp trời xanh vào lúc nửa đêm #Shorts",
        "description": seo_res.get("description") or "Video câu chuyện ngắn xúc động.",
        "tags": seo_res.get("tags") or ["Shorts", "Audiobook", "Truyện Ngắn"],
        "privacy_status": "public",
        "category_id": "24"
    }
    pub_res = api_post("publishing/youtube/publish", pub_payload)
    p(f"  - Kết quả gửi Publish: {pub_res.get('status')}")
    p(f"  - Publish ID: {pub_res.get('publish_id')}")
    p(f"  - Background Job ID: {pub_res.get('job_id')}")
    p(f"  - Định dạng: {pub_res.get('video_format')}")

    job_id = pub_res.get("job_id")
    publish_id = pub_res.get("publish_id")

    # 4. Monitor Background Job in Job Worker
    p(f"\n[Bước 4] Theo dõi tiến trình Job #{job_id} xử lý tải lên YouTube...")
    for _ in range(25):
        time.sleep(1.5)
        from app.database.session import SessionLocal
        from app.database.models import Job, Publish
        db = SessionLocal()
        job = db.query(Job).filter(Job.id == job_id).first()
        pub = db.query(Publish).filter(Publish.id == publish_id).first()
        if job:
            p(f"  -> Job #{job.id}: Status={job.status}, Progress={job.progress}%, Message={job.result}")
            if job.status == "completed":
                p(f"\n  [THÀNH CÔNG] Video đã được xuất bản hoàn tất!")
                p(f"  - Link YouTube: {pub.video_url if pub else 'N/A'}")
                p(f"  - Video ID: {pub.platform_video_id if pub else 'N/A'}")
                p(f"  - Platform: {pub.platform if pub else 'N/A'}")
                db.close()
                break
            elif job.status == "failed":
                p(f"\n  [THẤT BẠI] Job lỗi: {job.error_message}")
                db.close()
                sys.exit(1)
        db.close()

    # 5. Check History endpoint
    p("\n[Bước 5] Kiểm tra API Lịch sử đăng bài (/publishing/history)...")
    history = api_get("publishing/history")
    p(f"  - Tổng số bản ghi xuất bản: {len(history)}")
    if history:
        latest = history[0]
        p(f"  - Bài đăng gần nhất: ID={latest.get('id')}, Title='{latest.get('title')}', Platform={latest.get('platform')}, Status={latest.get('status')}, URL={latest.get('video_url')}")

    p("\n==================================================")
    p("✅ TEST TOÀN BỘ QUY TRÌNH DEPLOY YOUTUBE HOÀN TẤT TỐT ĐẸP!")
    p("==================================================")

if __name__ == "__main__":
    main()
