# FFmpeg Video Presets (TikTok 9:16 Vertical Format)

Tài liệu cấu hình chuỗi bộ lọc (Filter Graph) nâng cao của FFmpeg cho hệ thống **AI Movie Content Factory**.

---

## 1. Preset 1: Blurred Background Stack 9:16 (Khuyên Dùng)
Đặt video gốc ở chính giữa màn hình, phần trên và dưới là hình ảnh phóng to và làm mờ (Blur) của chính video đó.

```bash
ffmpeg -i source_video.mp4 -i voiceover.mp3 -filter_complex "\
[0:v]scale=1080:1920:force_original_aspect_ratio=increase,boxblur=20:5,setsar=1[bg]; \
[0:v]scale=1080:608,setsar=1[fg]; \
[bg][fg]overlay=0:(1920-608)/2[v_out]" \
-map "[v_out]" -map 1:a -c:v libx264 -preset fast -crf 22 -c:a aac -b:a 192k -shortest output.mp4
```

---

## 2. Preset 2: Audio Ducking (Hòa Trộn Nhạc Nền BGM & Giọng Đọc)
Tự động hạ âm lượng nhạc nền xuống 15-20% khi có giọng đọc review và tự động tăng lên khi có khoảng nghỉ (sử dụng bộ lọc `sidechaincompress` của FFmpeg):

```bash
ffmpeg -i voiceover.mp3 -i bgm.mp3 -filter_complex "\
[1:a]volume=0.35[bgm_base]; \
[bgm_base][0:a]sidechaincompress=threshold=0.1:ratio=5:attack=100:release=500[bgm_ducked]; \
[0:a][bgm_ducked]amix=inputs=2:duration=first:dropout_transition=2[a_out]" \
-map "[a_out]" -c:a aac -b:a 192k mixed_audio.aac
```

---

## 3. Preset 3: Bộ Lọc Chống Quét Bản Quyền (Anti-Shadowban Filter)
Tự động can thiệp nhẹ vào video để thay đổi chữ ký số (hash), tránh bị thuật toán nhận diện trùng lặp:

```bash
ffmpeg -i input.mp4 -filter_complex "\
[0:v]setpts=0.98039*PTS,hflip,eq=contrast=1.03:brightness=0.02:saturation=1.05[v_out]; \
[0:a]atempo=1.02[a_out]" \
-map "[v_out]" -map "[a_out]" -c:v libx264 -crf 21 output_safe.mp4
```
*Giải thích:* Tăng tốc độ 2% (`atempo=1.02`), lật ngang nhẹ (`hflip`), tăng nhẹ độ tương phản và màu sắc (`eq`).

---

## 4. Preset 4: Ghép Phụ Đề Động ASS (Kinetic Word-by-Word Subtitles)
Ghép phụ đề ASS với font hiện đại và hiệu ứng đổi màu từng từ:

```bash
ffmpeg -i video_input.mp4 -vf "ass=subtitles_kinetic.ass" -c:v libx264 -preset fast -crf 22 -c:a copy final_tiktok_video.mp4
```

---

## 5. Chuẩn Hóa Âm Thanh Toàn Cục (Loudness Normalization)
Áp dụng bộ lọc `loudnorm` để đảm bảo âm lượng đạt chuẩn TikTok (-14 LUFS):

```bash
ffmpeg -i raw_voice.wav -af loudnorm=I=-14:LRA=7:TP=-1.5 normalized_voice.wav
```
