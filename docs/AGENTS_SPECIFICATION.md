# 11 AI Agents Specification (Prompts & I/O Schemas)

Tài liệu đặc tả chi tiết vai trò, nguyên tắc thực thi và cấu trúc dữ liệu Input/Output của 11 AI Agent trong hệ thống **AI Movie Content Factory**.

---

## 1. Movie Hunter
- **Mục tiêu:** Tìm kiếm và thu thập thông tin phim theo tiêu chí người dùng đặt ra (thể loại, năm phát hành, điểm đánh giá).
- **Input:** `HunterQuery(genre: str, min_year: int, min_rating: float, limit: int)`
- **Output:** `List[MovieCandidate(title: str, year: int, synopsis: str, potential_score: float)]`
- **Nguyên tắc:** Lọc bỏ hoàn toàn các phim đã có trong cơ sở dữ liệu (`movies` table).

---

## 2. Movie Analyst
- **Mục tiêu:** Đọc hiểu cốt truyện, bóc tách các cao trào cảm xúc, plot twist, điểm gây sốc và quyết định chia phim thành bao nhiêu video ngắn.
- **Input:** `MovieDetail(title: str, synopsis: str, duration_minutes: int)`
- **Output:** `AnalysisResult(plot_summary: str, highlights: List[str], twists: List[str], recommended_episodes: int, target_audience: str, mood_tone: str)`

---

## 3. Script Writer
- **Mục tiêu:** Chuyển hóa phân tích cốt truyện thành kịch bản review ngắn hấp dẫn cho TikTok (60s - 120s / tập).
- **Input:** `ScriptRequest(movie_info: MovieDetail, analysis: AnalysisResult, episode_number: int, tone: str)`
- **Output:** `ScriptContent(episode: int, narrative_text: str, scene_cues: List[SceneCue], estimated_duration: int)`
- **Nguyên tắc:** Văn phong tự nhiên, câu từ cô đọng, giữ đúng sự thật nội dung phim, không thêm thắt tình tiết sai lệch.

---

## 4. Hook Generator
- **Mục tiêu:** Tạo ra 3 đến 5 câu mở đầu (Hook) cực mạnh trong 1-3 giây đầu tiên để giữ chân người xem lướt qua.
- **Input:** `HookRequest(script_content: str, style: str)`
- **Output:** `HookCandidates(hooks: List[HookItem(text: str, score: float, rationale: str)], selected_hook: str)`

---

## 5. Scene Selector & Slicer
- **Mục tiêu:** Sử dụng `PySceneDetect` bóc tách video gốc thành các đoạn clip 2-5s, sau đó AI chọn và ghép các đoạn clip phù hợp nhất với từng câu thoại kịch bản.
- **Input:** `SceneMatchRequest(script_scenes: List[SceneCue], media_source_path: str)`
- **Output:** `Timeline(cuts: List[VideoCut(clip_path: str, start_time: float, end_time: float, text_segment: str)])`
- **Nguyên tắc:** Không dùng cảnh quá 5 giây liên tục để giữ nhịp độ nhanh cho video TikTok.

---

## 6. Voice Agent
- **Mục tiêu:** Chuyển văn bản kịch bản thành giọng đọc tự nhiên (TTS), tự động chuẩn hóa âm lượng (`loudnorm`) và xuất file audio kèm timestamps.
- **Input:** `TTSRequest(text: str, voice_id: str, speed: float, provider: str)`
- **Output:** `AudioResult(audio_path: str, duration_seconds: float, word_timestamps: List[WordTime])`
- **Engine hỗ trợ:** `edge-tts` (Local/Miễn phí 100%), OpenAI TTS, ElevenLabs.

---

## 7. Subtitle Agent (Kinetic ASS Engine)
- **Mục tiêu:** Tạo phụ đề động chuẩn ASS (Advanced SubStation Alpha) với hiệu ứng đổi màu theo từng từ được đọc (Karaoke / Kinetic Highlight), font chữ hiện đại viền đen.
- **Input:** `SubtitleRequest(word_timestamps: List[WordTime], style_preset: str)`
- **Output:** `SubtitleResult(ass_path: str, srt_path: str, entries_count: int)`

---

## 8. Video Editor (FFmpeg Engine)
- **Mục tiêu:** Tổng hợp Video Cuts + Audio TTS + Nhạc nền (BGM với Audio Ducking) + Subtitles + Bộ lọc Anti-Shadowban thành video 9:16 (1080x1920).
- **Input:** `RenderRequest(timeline: Timeline, audio_path: str, bgm_path: str, ass_path: str, watermark: str)`
- **Output:** `RenderResult(video_path: str, file_size: int, duration: float, fps: int)`

---

## 9. QA Agent
- **Mục tiêu:** Kiểm định tự động chất lượng video trước khi chuyển sang bước xuất bản.
- **Input:** `QAInspectionRequest(video_path: str, expected_duration: float)`
- **Output:** `QAReport(passed: bool, checks: Dict[str, bool], issues: List[str])`
- **Tiêu chí:** Không có khung đen (black frames), không mất tiếng, âm lượng đúng chuẩn (-14 LUFS), khớp độ dài, có phụ đề rõ ràng.

---

## 10. SEO Agent
- **Mục tiêu:** Sinh Metadata tối ưu hóa tìm kiếm cho TikTok.
- **Input:** `SEORequest(movie_title: str, episode: int, hook_text: str)`
- **Output:** `SEOPack(title: str, caption: str, hashtags: List[str], cover_text: str)`

---

## 11. Analytics Agent
- **Mục tiêu:** Thu thập số liệu tương tác sau khi đăng, rút ra bài học tối ưu hóa cho các kịch bản tiếp theo.
- **Input:** `AnalyticsData(views: int, likes: int, shares: int, retention_rate: float)`
- **Output:** `OptimizationInsight(hook_effectiveness_score: float, topic_rating: str, recommendations: List[str])`
