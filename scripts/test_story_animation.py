import sys
import os
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import asyncio
from pathlib import Path
from app.story.story_animation_engine import StoryAnimationEngine

async def main():
    title = "Món Bánh Bất Ngờ Của Bé Miu"
    content = (
        "Buổi chiều hôm ấy, bé Miu lon ton vào bếp, bày bừa đủ thứ từ bột mì, trứng gà cho đến sữa tươi để trổ tài làm bánh.\n"
        "Anh hai đứng ngoài cửa nhìn vào, mặt đầy ngao ngán thì thầm: \"Sắp làm chuột bạch thử món mới của nó rồi...\"\n"
        "Chị gái cũng thở dài thườn thượt: \"Hic, lại chuẩn bị phải dọn chiến trường rồi đây!\"\n"
        "Ba mươi phút sau...\n"
        "Bé Miu bưng chiếc bánh kem ra bàn, cười tít mắt reo lên: \"Tadaa! Bánh kem thơm phức hảo hạng ra lò rồi nè!\"\n"
        "Cả anh hai và chị gái đều trợn tròn mắt kinh ngạc, đồng thanh thốt lên: \"Wow! Không thể tin được, đẹp mắt và thơm ngon quá đi mất!\""
    )
    comic_path = "media/working/stories/comic_cake_story.png"
    
    print("--- BẮT ĐẦU PIPELINE HOẠT HÌNH ĐA PHÂN CẢNH NHÂN VẬT (CHUẨN PRINTFILM) ---")
    output_video = await StoryAnimationEngine.render_story_animation(
        story_id=5,
        title=title,
        content=content,
        author="Truyện Tranh Gia Đình",
        reference_image_path=comic_path if Path(comic_path).exists() else None,
        aspect_ratio="9:16",
        bgm_name="suspense_bgm.mp3",
        progress_callback=lambda pct, msg: print(f"[{int(pct*100)}%] {msg}")
    )
    print(f"\n>>> VIDEO HOẠT HÌNH HOÀN THÀNH: {output_video}")

if __name__ == "__main__":
    asyncio.run(main())
