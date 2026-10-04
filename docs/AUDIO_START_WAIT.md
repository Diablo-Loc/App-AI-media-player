# Chờ chuẩn bị EQ trước khi phát bài mới — 04/10/2026

User cho phép thêm khoảng nghỉ im lặng/video chưa phát khi chọn hoặc chuyển bài để tránh reload ngắt giữa bài. Chỉ đường **EQ tùy chọn đang bật** dùng trạng thái chờ mới. Nguyên bản và cân bằng trực tiếp EQ-off giữ phát ngay như phase trước; không thêm delay cố định vào mọi bài.

## Hành vi

- Chọn bài/Next/Previous qua `MainWindow.on_media_clicked`: dừng bài cũ, nạp metadata nguồn gốc nhưng chưa gọi play, chuẩn bị EQ dưới nền. Phụ đề bị chặn trong lúc chờ, cue/dữ liệu/timing không thay đổi.
- Status bar hiện **Chuẩn bị âm thanh…** và progress nhỏ; play/pause trên playback bar/space/mini vẫn ghi nhận ý định. Nút pause trong lúc chờ khiến bài sẵn sàng vẫn paused; hardware play/pause qua adapter đầu phiên đặt trạng thái rõ ràng. SMTC báo chưa phát trong lúc chờ.
- Khi bản EQ sẵn sàng, áp gain trước khi phát, nạp nguồn xử lý, khôi phục vị trí/rate/tracks/loops và chỉ bắt đầu playback trên nguồn đó. Cache nhanh vẫn giữ video track mặc định khi metadata gốc chưa kịp tải.
- Tắt EQ lúc chờ: dùng lại âm gốc và bỏ kết quả EQ muộn. Đổi bài/preset nhanh: request mới nhất thắng. Tua/rate/pause trong lúc chờ được giữ khi sẵn sàng.
- Chuẩn bị tối đa 15 giây: lỗi hoặc quá hạn hủy job sở hữu và dùng âm gốc cho lần chọn đó, không tự thử lại liên tục. Decoder load vẫn có deadline 8 giây; nếu cả nguồn gốc lỗi thì thoát chờ, cho chọn bài khác. Không có GUI-thread wait khi tương tác.
- Callback decoder lỗi có thể tiếp tục phát `InvalidMedia` sau `errorOccurred`. Khi đang chờ selection, fallback dùng owned single-shot timer 0 và transition identity để tránh lỗi cũ xóa source gốc vừa tải. Không thay đường hồi phục của transition giữa bài trước đó.

Đây là **dời thời điểm phát đến sau chuẩn bị**, không loại bỏ reload: source gốc vẫn được nạp metadata rồi đổi sang bản EQ. Bật/tắt/chỉnh EQ **giữa bài đang phát** vẫn có khoảng ngắt như v1. Không thêm EQ 5 dải/lọc nhiễu hoặc engine DSP trực tiếp trong phase này.

## Phạm vi và bảo toàn

Giữ một QMediaPlayer/QAudioOutput/video widget/native engine. Giữ profile/preset/cache keys/1 GiB EQ cache/256 record loudness cache, below-normal worker và latest cancellation. Không migrate profile hoặc thay âm gốc; feature vẫn OFF mặc định. Không sửa model/ASR/translation/schema/ID/timing/fade/playlist/filter/download/editor/native frame.

MainWindow có năm adapter được review: chọn bài gọi `audio_effects.play_source`; toggle/hardware handlers ghi nhận ý định khi chờ; mini sync dùng ý định đó để icon thống nhất. `control.audio_effects` sở hữu state/timer/indicator và transition; popup chỉ sửa câu mô tả. [Snapshot/hash/diff mới](audio-start/reviewed-sources.json) phục hồi source v2 trước khi các gate cũ chạy; manifest v1/v2 frozen, không recapture. Không commit/build/stage/dependency upgrade hoặc dọn dữ liệu user.

## Kiểm chứng

Python 3.11/Qt 6.10.1, Windows, Qt offscreen với decoder thật và audio muted:

- **270 total =259 pass +11 historical skip**, 70,169 giây; [full log](audio-start/test-results.txt). Các dòng synthetic save/read-only ERROR là fault injection của suite, không phải test thất bại.
- 12 regression mới: cold/cache/repeat selection, original never plays first, preserved owners/volume/device, queued pause/seek/rate/hardware/mini intent, off/cancel/error/timeout/shutdown, rapid latest-source/preset, invalid processed decoder fallback, integration subtitle dispatch/full queue và reentrant seek selection.
- **89 tests đạt DPI 200%**, 54,180 giây: [log](audio-start/dpi-200-tests.txt).
- [Diff check](audio-start/diff-check.txt) đạt; [31/31 saved hashes](audio-start/saved-file-check.json) so với [snapshot đầu lượt này](audio-start/saved-before.json) không đổi. Không dùng baseline phase trước để ghi đè index/cache đã được người dùng cập nhật.

Probe riêng [8 video có sẵn](audio-start/media-probe.json), tổng 198,24 MiB, tách khỏi test suites, settings/cache trong TemporaryDirectory:

| Kiểm tra | Kết quả trên máy này |
| --- | --- |
| Cold EQ: chọn bài đến position >50 ms sau khi bắt đầu phát | **5,94–8,29 giây** |
| Cache EQ: cùng phép đo, có nạp source/decoder | **0,21–0,26 giây** |
| Số tool processes mỗi cold/cache selection | **3 / 0**, chạy tuần tự qua worker sở hữu |
| Source changes cold selection | **2**, nạp gốc metadata rồi bản EQ |
| Playing transitions cold và cache | **1 mỗi selection**, original chưa phát |
| Video track sau khi phát | **0 trên cả 16 selection** |
| Source SHA | **8/8 không đổi** |

Không so con số trên với 0,53–1,10 ms **JSON measurement lookup** của normalization: đó là công việc khác. Không tuyên bố pipeline EQ nhanh hơn; thời gian xử lý vốn có nay nằm trước playback. Không thêm vài giây nghỉ nhân tạo nếu cache đã có. Replay: `python -m tools.probe_audio_start`; [stdout](audio-start/media-probe.txt).

Các probe source/state không đo DAC, cảm nhận tiếng pop/nghe A/B, Windows compositor FPS, multi-device/driver/all-container hoặc EXE/update. Những nghiệm thu đó vẫn riêng, không chứng nhận toàn app đạt chuẩn thương mại từ offscreen tests.

## Tối ưu tiếp theo có ích

Đề xuất **chuẩn bị trước duy nhất bài kế tiếp** đã được triển khai trong phase tiếp theo: [AUDIO_NEXT_PREFETCH.md](AUDIO_NEXT_PREFETCH.md). Dùng chung một worker/process, chỉ EQ-on, có hủy/promotion/shuffle/seek/AI/budget gates và probe 8 video. Số đo trên máy yếu/native vẫn cần nghiệm thu riêng.

EQ 5 dải/giảm chói và denoise chọn theo bài vẫn theo [phương án chất âm](AUDIO_ENHANCEMENT_PLAN.md). Giảm nhiễu không tự bật mọi bài; mọi xử lý có reset/bypass và không sửa nguồn. DSP không reload hoàn toàn vẫn cần phase audio-routing riêng.
