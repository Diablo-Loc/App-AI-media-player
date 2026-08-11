# BoTube Project Structure Documentation

## Tổng quan dự án
BoTube là một media player với các tính năng AI-powered cho subtitle, translation và xử lý âm thanh. Ứng dụng được xây dựng bằng Python sử dụng PySide6 cho giao diện người dùng, tích hợp các công nghệ AI như Whisper cho speech recognition, và các thư viện xử lý âm thanh như librosa.

## Architecture Overview
- **UI Layer**: PySide6-based interface (MainWindow, pages, components)
- **Controller Layer**: Business logic coordination (AppController, AIController)
- **Core Layer**: Core functionality (MediaLibrary, SubtitleManager, MediaControl)
- **AI Pipeline**: Speech recognition, translation, alignment (Whisper, NLLB, forced alignment)
- **Download Layer**: Media downloading (yt-dlp integration)
- **Storage Layer**: File management, caching, persistence

## Cấu trúc thư mục chính

### Root Level Files
- **README.md**: Tài liệu hướng dẫn sử dụng, cập nhật và build ứng dụng.
- **requirements.txt**: Danh sách dependencies Python cần thiết.
- **version.json**: Thông tin phiên bản ứng dụng.
- **config.example.json**: File cấu hình mẫu.
- **build_app.py**: Script build ứng dụng thành executable.
- **build_app_for_update.py**: Script build cho update patches.
- **patch_build.py**: Script tạo patch update.
- **update_helper.bat/.sh**: Scripts hỗ trợ update.
- **BoTube.spec**: Cấu hình PyInstaller cho build full app.
- **BoTube_patch.spec**: Cấu hình PyInstaller cho build patch.
- **LOGIC_CHECK.md**: Tài liệu kiểm tra logic.
- **TODO.md**: Danh sách công việc cần làm.
- **Bugs.txt**: Danh sách lỗi đã biết.
- **error_log.txt**: Log lỗi.

### app/ - Thư mục chính của ứng dụng
Chứa toàn bộ code nguồn của ứng dụng.

#### app/run_app.py
- **Chức năng**: Entry point chính của ứng dụng.
- **Nhiệm vụ**: 
  - Thiết lập logging và exception handling.
  - Kiểm tra dependencies hệ thống (FFmpeg/FFprobe).
  - Khởi tạo các components chính: MediaLibrary, SubtitleManager, AIController, AppController, MainWindow.
  - Chạy event loop của QApplication.

#### app/config.py
- **Chức năng**: Quản lý cấu hình ứng dụng.
- **Nhiệm vụ**: Load/save settings từ file JSON, quản lý các tùy chọn như đường dẫn, theme, AI settings.

#### app/downloader.py
- **Chức năng**: Xử lý download media từ internet.
- **Nhiệm vụ**: Tải video/âm thanh từ YouTube hoặc các nguồn khác, quản lý queue download, progress tracking.

#### app/paths.py
- **Chức năng**: Quản lý đường dẫn thư mục trong ứng dụng.
- **Nhiệm vụ**: Định nghĩa và resolve các path cho storage, input, temp, assets, models, etc. Xử lý cả development và packaged app paths.

#### app/updater.py
- **Chức năng**: Xử lý cập nhật ứng dụng.
- **Nhiệm vụ**: Kiểm tra phiên bản mới từ GitHub, download và áp dụng update, xử lý patch vs full update.

#### app/worker.py
- **Chức năng**: Worker threads cho các tác vụ nền.
- **Nhiệm vụ**: Xử lý các tác vụ không đồng bộ như AI processing, download, thumbnail generation. Kế thừa từ QThread hoặc threading.Thread.

#### app/ai/ - Thư mục xử lý AI
- **ai/pipeline.py**: Pipeline xử lý AI tổng thể - orchestrate ASR, translation, alignment.
- **ai/whisper_engine.py**: Engine xử lý speech recognition với Whisper - load model, transcribe audio.

#### app/control/ - Thư mục controllers
- **control/ai_controller.py**: Controller quản lý các tác vụ AI.
  - Chức năng: Quản lý vòng đời của AIWorker threads, phát signals cho status/progress/job completion, khởi động và dừng AI jobs.
- **control/ai_process_manager.py**: Quản lý processes cho AI - multiprocessing cho heavy tasks.
- **control/app_controller.py**: Controller chính của ứng dụng, kết nối UI và logic.
  - Chức năng: Điều phối giữa MainWindow, MediaLibrary, AIController, SubtitleManager.

#### app/core/ - Thư mục core logic
- **core/media_control.py**: Điều khiển playback media.
- **core/media_library.py**: Quản lý thư viện media files.
  - Chức năng: Scan thư mục, lấy metadata với FFprobe, cache thông tin, quản lý thumbnails.
- **core/subtitle_manager.py**: Quản lý subtitles.
  - Chức năng: Lưu trữ subtitles ở định dạng JSON (source) và ASS (render), quản lý index mapping media ID với filenames, xử lý các mode subtitle (JP/EN/VI), clean và format segments, import/export subtitles.
- **core/subtitle_renderer.py**: Render subtitles lên video.

#### app/download_core/ - Thư mục download
- **download_core/download_worker.py**: Worker download files.
- **download_core/get_title_worker.py**: Worker lấy title từ URL.
- **download_core/utils.py**: Utilities cho download.
- **download_core/yt_dlp.py**: Wrapper cho yt-dlp library.

#### app/job/ - Thư mục job management
- **job/job_manager.py**: Quản lý jobs/tác vụ.
- **job/job_state.py**: Trạng thái của jobs.

#### app/pipeline/ - Thư mục xử lý pipeline
- **pipeline/aligner.py**: Align text với audio.
- **pipeline/asr_engine.py**: Automatic Speech Recognition.
- **pipeline/extractor.py**: Extract features từ audio.
- **pipeline/forced_aligner.py**: Forced alignment.
- **pipeline/jp_normalizer.py**: Normalize text tiếng Nhật.
- **pipeline/lyric_formatter.py**: Format lyrics.
- **pipeline/postprocess.py**: Post-processing.
- **pipeline/utils.py**: Utilities cho pipeline.
- **pipeline/vad.py**: Voice Activity Detection.
- **pipeline/vocal_separator.py**: Tách vocal từ audio.

#### app/subtitle/ - Thư mục xử lý subtitle
- **subtitle/config.py**: Cấu hình subtitle.
- **subtitle/converter.py**: Convert giữa các format subtitle (SRT, ASS, LRC, etc.).
- **subtitle/engine.py**: Engine xử lý subtitle - parse, timing, styling.
- **subtitle/mode.py**: Định nghĩa các mode subtitle (JP only, JP+EN, JP+EN+VI).
- **subtitle/model.py**: Models cho subtitle data structures.
- **subtitle/models.py**: Các model classes cho subtitle processing.
- **subtitle/profile.py**: Profiles cho subtitle styling và formatting.
- **subtitle/storage.py**: Storage layer cho subtitles - save/load từ disk.
- **subtitle/ass/**: Xử lý format ASS subtitle - rendering, styling, effects.

#### app/test/ - Thư mục test
- **test/main.py**: Main test script.
- **test/test_*.py**: Các file test cho các module.

#### app/thumbnail/ - Thư mục thumbnail
- **thumbnail/thumbnail_manager.py**: Quản lý tạo thumbnail.
- **thumbnail/thumbnail_workers.py**: Workers tạo thumbnail.

#### app/translate/ - Thư mục translation
- **translate/cache.py**: Cache cho translations.
- **translate/nllb.py**: Sử dụng NLLB model cho translation.
- **translate/online_logic.py**: Logic translation online.
- **translate/pipeline.py**: Pipeline translation.
- **translate/translator.py**: Main translator class.

#### app/ui/ - Thư mục giao diện người dùng
- **ui/main_window.py**: Cửa sổ chính của ứng dụng.
  - Chức năng: Chứa các UI components (PlaybackBar, MediaCard, SubtitleLayer), quản lý các pages (HomePage, LibraryPage, DownloadPage, SettingsPage), xử lý media playback với QMediaPlayer, tích hợp MiniPlayer và Sidebar navigation.
- **ui/media_card.py**: Component hiển thị thông tin media item.
- **ui/media_player.py**: Player media với controls.
- **ui/playback_bar.py**: Thanh điều khiển playback (play/pause, seek, volume).
- **ui/styles.py**: Styles và themes cho UI.
- **ui/vol_panel.py**: Panel điều khiển volume.
- **ui/nav/**: Navigation components - sidebar, menu.
- **ui/pages/**: Các trang UI - home, library, download, settings, for you.
- **ui/subs_ui/**: UI cho subtitles - subtitle layer, settings panel.

### bin/ - Thư mục binaries
Chứa FFmpeg và các binaries cần thiết cho media processing.

### build/ - Thư mục build output
- **build/BoTube/**: Output từ PyInstaller - executable, libraries, data files.

### data/ - Thư mục data
- **data/thumbnails/**: Thumbnails được tạo cho media files.

### icon/ - Thư mục icons
Chứa icon của ứng dụng cho UI và taskbar.

### input/ - Thư mục input
Cho files input của user - media files để process.

### installer/ - Thư mục installer
Scripts và files cho tạo installer (NSIS, Inno Setup, etc.).

### models/ và models_cache/ - Thư mục models AI
- **models/models--Systran--faster-whisper-medium/**: AI models cho speech recognition.
- **models_cache/**: Cache cho downloaded models.

### output/ - Thư mục output
- **output/translation_cache.json**: Cache cho translations.

### storage/ - Thư mục storage
- **storage/app_config.json**: Cấu hình ứng dụng.
- **storage/library_cache.json**: Cache thư viện media.
- **storage/setting.json**: Settings người dùng.
- **storage/subtitles/**: Subtitles được lưu trữ.
- **storage/temp/**: Files tạm thời.
- **storage/thumbnails/**: Thumbnails cached.

### temp_test_ai/ - Thư mục test AI
Files test cho AI features - sample subtitles, audio clips.

### test/ - Thư mục test khác
Additional test files và scripts.

## Workflow chính của ứng dụng

1. **Khởi động**: run_app.py → Kiểm tra FFmpeg → Khởi tạo MediaLibrary, SubtitleManager, AIController, MainWindow.

2. **Scan Media**: MediaLibrary scan thư mục → Lấy metadata với FFprobe → Lưu cache → Tạo thumbnails.

3. **AI Processing**: User chọn file → AIController khởi động AIWorker → Pipeline xử lý: ASR (Whisper) → Translation (NLLB) → Alignment → Subtitle generation.

4. **Subtitle Management**: SubtitleManager lưu JSON source → Render ASS theo mode → SubtitleRenderer hiển thị lên video.

5. **Playback**: MainWindow + QMediaPlayer → SubtitleLayer overlay subtitles → PlaybackBar controls.

6. **Download**: DownloadPage → yt_dlp download → MediaLibrary add to library.

## Dependencies chính
- **PySide6**: UI framework
- **librosa/soundfile**: Audio processing
- **faster-whisper**: Speech recognition
- **transformers**: AI models
- **torch**: Machine learning
- **FFmpeg**: Media processing
- **yt-dlp**: Video download

## Hướng dẫn maintain và debug

### Khi fix bug:
1. **Xác định module**: Dùng file này để tìm module liên quan (ví dụ: bug playback → media_player.py hoặc media_control.py)
2. **Check logs**: Xem error_log.txt và logging trong code
3. **Test riêng**: Chạy test files trong test/ hoặc app/test/

### Khi nâng cấp:
1. **Update dependencies**: Check requirements.txt
2. **Test pipeline**: AI pipeline có thể cần adjust khi update models
3. **UI changes**: MainWindow và các components trong ui/

### Build và deploy:
- **Development**: Chạy trực tiếp python app/run_app.py
- **Production**: python build_app.py → dist/BoTube/BoTube.exe
- **Update**: python patch_build.py → tạo patch cho update