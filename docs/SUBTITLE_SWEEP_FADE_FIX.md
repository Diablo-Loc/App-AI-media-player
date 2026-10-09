# Erased sweep at cue end

Lỗi tái hiện ở UI thật khi `subtitle_effects.enabled`, `trail` khác `none` và
`erase_passed` cùng bật: lúc cue hết hạn, `SubtitleLayer._smart_hide()` gọi
`SubtitleEffects.clear()` trước khi fade-out 220 ms chạy. Việc clear làm renderer
quay về glyph pass bình thường, nên toàn câu hiện lại trong lúc QLabel đang fade.
Đây là nguyên nhân câu vừa quét xong nháy lại rồi mới chuyển sang cue tiếp theo.

Sửa theo hướng chỉ đổi trạng thái vẽ:

- Nếu đúng chế độ erase sweep và cue đủ 160 ms, chốt `scan_progress = 1`, dừng
  timer hạt/entry và giữ sweep mask trong fade-out.
- Khi widget thực sự ẩn, event filter dọn effect/cache như trước.
- Fade 220 ms, thời điểm cue, text, endpoints, playback clock, seek, saved settings
  và renderer export không đổi. Cue ngắn, effect OFF, erase OFF, fade OFF và hide tức
  thời vẫn đi theo đường clear cũ.

Regression mới kiểm tra rằng câu không bị phục hồi trong fade-out và source adapter
chỉ bóc đúng hai thay đổi của phase này trước khi chạy các manifest lịch sử. Các
manifest cũ được giữ nguyên.

Kiểm chứng runtime cần chạy `tests.test_subtitle_effects`; Python 3.11 hiện cấu hình
trong `venv/pyvenv.cfg` không còn trên máy, nên test native Qt phải chạy lại khi
interpreter khả dụng. Không có thay đổi ASR, phụ đề đã lưu, audio, video player,
export, hay thời gian cue.
