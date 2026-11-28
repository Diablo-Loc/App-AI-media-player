'use strict';

const REPO_API = 'https://api.github.com/repos/Diablo-Loc/App-AI-media-player/releases/latest';
const DEFAULT_VERSION = '6.1.0';

const I18N = {
  vi: {
    _title: 'BoTube 6.1 — AI Media Player, Hi-Fi Audio Studio & YouTube Online',
    skip: 'Chuyển thẳng tới nội dung chính',
    nav_showcase: 'Giao diện',
    nav_features: 'Tính năng',
    nav_whats_new: 'Điểm mới 6.1',
    nav_install: 'Cài đặt',
    nav_download: 'Tải Windows',
    hero_badge: 'Phiên bản 6.1.0 · Dành cho Windows 10/11 64-bit',
    hero_title: 'Trình phát Media AI, Phòng thu Hi-Fi 64-bit & YouTube Online',
    hero_lead:
      'Hội tụ thư viện Offline chuẩn Bit-Pure WASAPI Exclusive và không gian YouTube Online 4K Hi-Fi tách biệt hoàn toàn — kèm Két Cookie mã hóa Windows DPAPI, phụ đề AI Whisper song ngữ, Karaoke từng chữ và xuất video tăng tốc GPU NVIDIA NVENC.',
    hero_dl_btn: 'Tải BoTube_Setup.exe',
    hero_releases_btn: 'Xem bản phát hành',
    pill_platform: 'Windows 10 / 11 64-bit',
    pill_dpapi: 'Két Cookie mã hóa Windows DPAPI',
    pill_sha: 'Xác thực SHA-256 & Auto-Update',
    pill_upgrade: 'Nâng cấp 5.0 / 6.0 → 6.1 giữ 100% dữ liệu',
    tab_ui: 'For You & Karaoke',
    tab_yt: 'YouTube Hi-Fi',
    tab_karaoke: 'Mô phỏng AMLL',
    tab_audio: 'Chuỗi 64-bit',
    demo_sub_vi: 'Giai điệu vang xa vượt qua bầu trời đêm đầy sao',
    demo_pause: 'Tạm dừng mô phỏng',
    demo_play: 'Chạy mô phỏng',
    screenshot_caption:
      'Giao diện Dark Studio thực tế bằng PySide6 / Qt6 với AMLL Word Karaoke, phiên âm offline, hàng đợi thông minh và điều khiển âm thanh Hi-Fi.',
    yt_stage_caption:
      'YouTube Online Hi-Fi Studio tách biệt hoàn toàn: kết nối luồng ~0.14s, tự đồng bộ tài khoản qua Két Cookie DPAPI, Viên thuốc & Phụ đề AI BoTube.',
    chain_title: 'Đường truyền tín hiệu Bit-Pure 64-bit Float (Offline & YouTube)',
    chain_1: 'Giải mã không suy hao tệp cục bộ (FLAC, WAV, AAC, Opus, MP3) & luồng YouTube Opus Hi-Fi',
    chain_2: 'Chuẩn hóa EBU R128 (−14 LUFS), 10-Band / PEQ Squiglink, Minimum-Phase DAC & chống vỡ đỉnh 0 dBTP',
    chain_3: 'Xuất thẳng tới USB DAC rời, bỏ qua bộ trộn Windows + tự nối lại 4 tầng (≤0.5s) khi Bluetooth/DAC chuyển mạch',
    stats_heading: 'Thông số nổi bật',
    stat_dsp: 'Âm thanh Float DSP & WASAPI tự hồi phục (Offline + Online)',
    stat_yt: 'Khởi phát luồng YouTube 4K GPU & OPUS Hi-Fi tức thì',
    stat_dpapi: 'Két Cookie mã hóa theo tài khoản Windows, tự xóa file gốc',
    stat_nvenc: 'Xuất video kèm phụ đề 4K tăng tốc phần cứng GPU NVIDIA',
    gal_kicker: 'TRẢI NGHIỆM GIAO DIỆN THỰC TẾ',
    gal_heading: 'Mọi không gian nghe nhìn trong một ứng dụng desktop tinh gọn',
    gal_sub: 'Bấm vào bất kỳ màn hình nào bên dưới để phóng to toàn cảnh giao diện thực tế của BoTube 6.1.',
    gal_zoom: 'Phóng to ↗',
    gal1_badge: 'Offline Hi-Fi',
    gal1_title: 'For You · AMLL Karaoke từng chữ & Phiên âm',
    gal1_desc:
      'Quét lời khớp từng âm tiết chuẩn giọng hát, bật/tắt phiên âm Romaji / Pinyin / Hàn ngữ offline bằng phím R, quản lý danh sách phát và Bộ sưu tập mượt mà.',
    gal2_badge: 'Mới trên 6.1',
    gal2_title: 'YouTube Online Hi-Fi Studio — Đề xuất cá nhân & Đồng bộ DPAPI',
    gal2_desc:
      'Tự nạp Trang chủ đề xuất, Playlist, Video đã thích, Xem sau và Kênh đăng ký trực tiếp từ Két Cookie mã hóa Windows DPAPI. Tích hợp Viên thuốc Dynamic Island, chỉnh EQ trực tiếp và lọc chủ đề mượt mà.',
    gal3_badge: 'Video 4K · Audio-Only',
    gal3_title: 'Trình phát YouTube + Phụ đề AI BoTube & Mix Radio',
    gal3_desc:
      'Chuyển đổi tức thì giữa Video 4K GPU và Chỉ nghe Nhạc Hi-Fi 64-bit OPUS. Hỗ trợ 3 chế độ phụ đề (Tắt / YouTube CC / ✨ AI BoTube tự lưu cache), phân đoạn Chapters, Mini-Player PiP nổi và chuyển 1-Click sang Tải về.',
    gal4_badge: 'Audio Lab',
    gal4_title: 'Phòng đo kiểm chất âm & Nghe thử A/B',
    gal4_desc:
      'Đo trực tiếp trên cả bài hát Offline lẫn luồng YouTube: phổ tần số RTA, đáp tuyến pha ±180°, True-Peak 0 dBTP, THD+N 1 kHz và nghe thử đối chiếu A/B khớp độ lớn.',
    gal5_badge: 'Tùy biến linh hoạt',
    gal5_title: 'Cài đặt Studio & 3 Chế độ Không gian',
    gal5_desc:
      'Chọn dùng Chỉ Offline, Chỉ YouTube Online hay Cả hai. Mọi thay đổi ngôn ngữ Việt ↔ Anh, thiết bị DAC, model Whisper & dịch thuật đều tự lưu tức thì.',
    feat_kicker: 'KIẾN TRÚC PHÒNG THU TOÀN DIỆN',
    feat_heading: 'Mọi công cụ nghe nhìn AI chuyên sâu hội tụ trong một ứng dụng',
    feat_sub:
      'Tách biệt sạch sẽ giữa Thư viện Offline và YouTube Online, tối ưu tối đa CPU/RAM và bảo vệ dữ liệu cục bộ tuyệt đối trên Windows.',
    f0_title: 'YouTube Online 4K Hi-Fi & Két Cookie DPAPI',
    f0_desc:
      'Phát video 4K GPU mượt kết hợp âm thanh 64-bit WASAPI, Audio-Only, PiP nổi, Viên thuốc Dynamic Island và phụ đề AI tự lưu cache. Cookie mã hóa bằng Windows DPAPI và tự xóa sạch file gốc trong Downloads.',
    f1_title: 'Âm thanh Hi-Fi 64-bit & Tự hồi phục WASAPI',
    f1_desc:
      'Chuẩn hóa EBU R128 (−14 LUFS) khử clip 0 dBTP, 10-Band & Parametric EQ Squiglink/APO, WASAPI Exclusive cho DAC rời, tự nối lại 4 tầng (≤0.5s) khi thiết bị Bluetooth/DAC đổi trạng thái cùng Audio Lab A/B.',
    f2_title: 'Whisper AI CUDA & Fast Synced Lyrics',
    f2_desc:
      'Ưu tiên lời chuẩn LRCLIB / sidecar căn nhịp siêu tốc (< 1 giây), tự chuyển sang Faster-Whisper (Tiny → Large-v3) trên GPU NVIDIA CUDA hoặc CPU với 2 chế độ Lời bài hát & Hội thoại/Phim.',
    f3_title: 'Dịch đa mô hình AI & Đối soát Genius',
    f3_desc:
      'Dịch offline miễn phí bằng NLLB-200 hoặc dịch lời nhạc mượt mà qua Google Gemini, OpenAI (GPT-4o / GPT-5) và Anthropic Claude — kết hợp đối chiếu Genius kiểm định độ khớp từng câu.',
    f4_title: 'Karaoke từng chữ, Phiên âm & Hiệu ứng 60 FPS',
    f4_desc:
      'Hiệu ứng AMLL Sing mượt như Apple Music khớp từng chữ/âm tiết, tạo dòng phiên âm Romaji / Pinyin / Hàn ngữ hoàn toàn offline (phím R) cùng bộ hiệu ứng hạt quang học và typography 60 FPS.',
    f5_title: 'Xuất Video NVENC, Tải Gốc & Cập nhật SHA-256',
    f5_desc:
      'Gắn phụ đề + hiệu ứng vào video 16:9 / 9:16 / 4K tăng tốc GPU NVIDIA h264_nvenc, tải yt-dlp giữ nguyên âm thanh gốc, Bộ sưu tập + Smart Resume và cập nhật tự động GitHub Releases chuẩn SHA-256.',
    new_kicker: 'TIẾN HÓA QUA CÁC PHIÊN BẢN',
    new_heading: 'Có gì mới trên BoTube 6.1?',
    new_sub:
      'Máy đang cài BoTube 5.0 hoặc 6.0 chỉ cần chạy BoTube_Setup.exe bản 6.1 — trình cài đặt tự nâng cấp gọn gàng và bảo toàn 100% dữ liệu.',
    table_caption: 'So sánh tính năng giữa BoTube 5.0, 6.0 và 6.1',
    th_area: 'Hạng mục',
    r0_k: 'YouTube Online Hi-Fi',
    r0_v5: 'Chỉ tải về qua yt-dlp',
    r0_v6: 'Tải về chất lượng gốc',
    r0_v61: 'Tab YouTube 4K GPU + Hi-Fi 64-bit, AI Sub tự lưu cache, Audio-Only, PiP & Viên thuốc',
    r7_k: 'Đồng bộ & Bảo mật',
    r7_v5: 'Chưa hỗ trợ tài khoản',
    r7_v6: 'Hỗ trợ cookie tải về',
    r7_v61: 'Két Cookie mã hóa Windows DPAPI, tự xóa file Downloads, tự đồng bộ Trang chủ / Playlist / Đã thích',
    r1_k: 'Âm thanh & WASAPI',
    r1_v5: 'Preset cơ bản',
    r1_v6: 'Hi-Fi 64-bit, WASAPI, Audio Lab',
    r1_v61: 'Tự hồi phục WASAPI 4 tầng (≤0.5s) chống ngắt âm & đo kiểm Audio Lab trực tiếp trên YouTube',
    r2_k: 'Phụ đề & Karaoke',
    r2_v5: 'Quét theo câu cơ bản',
    r2_v6: 'Karaoke từng chữ, AMLL, Phiên âm R',
    r2_v61: 'Mở rộng AI BoTube lên YouTube + tùy chọn Whisper thuần (bỏ dịch) & đồng bộ giao diện phụ đề',
    r3_k: 'Xuất Video & Không gian',
    r3_v5: 'CPU libx264, 1 chế độ',
    r3_v6: 'GPU NVIDIA h264_nvenc ⚡',
    r3_v61: 'NVENC GPU + 3 Chế độ Hoạt động (Cả hai / Chỉ Offline / Chỉ YouTube Online) tối ưu RAM/CPU',
    r6_k: 'Cài đặt & Cập nhật',
    r6_v5: 'Cài thủ công, Tiếng Việt',
    r6_v6: 'Auto-Updater SHA-256, VI ↔ EN',
    r6_v61: 'Giữ trọn Auto-Updater SHA-256, song ngữ VI ↔ EN tức thì & nâng cấp giữ 100% dữ liệu',
    inst_kicker: 'BẮT ĐẦU TRONG 2 PHÚT',
    inst_heading: 'Cài mới hoặc nâng cấp lên 6.1 chỉ với 3 bước',
    s1_title: 'Tải BoTube_Setup.exe',
    s1_desc:
      'Tải bộ cài chính thức từ GitHub Releases. Nếu máy đã cài bản 5.0 hoặc 6.0, chỉ cần chạy trực tiếp bộ cài mới — toàn bộ thư viện, phụ đề và mô hình AI được giữ nguyên 100%.',
    s2_title: 'Chọn không gian & gói AI tùy chọn',
    s2_desc:
      'Nghe nhạc Hi-Fi, xem YouTube Online 4K và tải video hoạt động ngay. Khi cần tạo phụ đề tự động, mở Cài đặt → Tải / Cập nhật mô hình AI để cài Whisper / NLLB.',
    s3_title: 'Luôn tự động lên bản mới',
    s3_desc:
      'BoTube tự kiểm tra bản phát hành mới trên GitHub Releases, xác thực chữ ký SHA-256 và nâng cấp chỉ bằng một cú bấm ngay trong ứng dụng.',
    cta_title: 'Sẵn sàng trải nghiệm BoTube 6.1?',
    cta_desc: 'Miễn phí, tối ưu cho Windows 10/11 64-bit — nghe nhạc Hi-Fi Offline & YouTube Online trong một ứng dụng duy nhất.',
    cta_btn_dl: 'Tải BoTube 6.1 ngay',
    cta_btn_src: 'Xem mã nguồn GitHub',
    footer_copy: 'Trình phát Media AI, Âm thanh Hi-Fi & YouTube Online cho Windows · Phát hành chính thức qua GitHub Releases.',
  },
  en: {
    _title: 'BoTube 6.1 — AI Media Player, Hi-Fi Audio Studio & YouTube Online',
    skip: 'Skip to main content',
    nav_showcase: 'Showcase',
    nav_features: 'Features',
    nav_whats_new: "What's New 6.1",
    nav_install: 'Install',
    nav_download: 'Download Windows',
    hero_badge: 'Release 6.1.0 · Built for Windows 10/11 64-bit',
    hero_title: 'AI Media Player, 64-bit Hi-Fi Audio Studio & YouTube Online',
    hero_lead:
      'Unites a Bit-Pure WASAPI Exclusive offline library with a fully isolated 4K YouTube Online Hi-Fi Studio — backed by a Windows DPAPI Encrypted Cookie Vault, Whisper bilingual AI subtitles, word-level Karaoke, and NVIDIA NVENC video export.',
    hero_dl_btn: 'Download BoTube_Setup.exe',
    hero_releases_btn: 'View Releases',
    pill_platform: 'Windows 10 / 11 64-bit',
    pill_dpapi: 'Windows DPAPI Encrypted Cookie Vault',
    pill_sha: 'SHA-256 Verified Auto-Updater',
    pill_upgrade: '5.0 / 6.0 → 6.1 upgrade keeps 100% data',
    tab_ui: 'For You & Karaoke',
    tab_yt: 'YouTube Hi-Fi',
    tab_karaoke: 'AMLL Demo',
    tab_audio: '64-bit Chain',
    demo_sub_vi: 'A melody echoing far across the starlit midnight sky',
    demo_pause: 'Pause simulation',
    demo_play: 'Play simulation',
    screenshot_caption:
      'Authentic PySide6 / Qt6 Dark Studio UI with AMLL Word Karaoke, instant offline phonetics, smart queue, and Hi-Fi playback controls.',
    yt_stage_caption:
      'Fully isolated YouTube Online Hi-Fi Studio: ~0.14s stream startup, automatic account sync via DPAPI Cookie Vault, Pill Mode & BoTube AI Subtitles.',
    chain_title: 'Bit-Pure 64-bit Float Signal Path (Offline & YouTube)',
    chain_1: 'Lossless local decoding (FLAC, WAV, AAC, Opus, MP3) & native YouTube Opus Hi-Fi streaming',
    chain_2: 'EBU R128 loudness (−14 LUFS), 10-Band / Squiglink PEQ, Minimum-Phase DAC & 0 dBTP true-peak protection',
    chain_3: 'Direct WASAPI Exclusive output to external USB DACs + 4-tier automatic drop recovery (≤0.5s) on Bluetooth/DAC changes',
    stats_heading: 'Key Highlights',
    stat_dsp: 'Float Audio DSP & self-recovering WASAPI (Offline + Online)',
    stat_yt: 'Instant 4K GPU video & OPUS Hi-Fi YouTube stream resolution',
    stat_dpapi: 'Windows user-bound Cookie Vault with automatic source shred',
    stat_nvenc: 'Hardware-accelerated 4K subtitle video burn-in on NVIDIA GPU',
    gal_kicker: 'REAL INTERFACE SHOWCASE',
    gal_heading: 'Every listening & creation workspace in one focused desktop app',
    gal_sub: 'Click any screen below to inspect the full-resolution BoTube 6.1 desktop interface.',
    gal_zoom: 'Expand ↗',
    gal1_badge: 'Offline Hi-Fi',
    gal1_title: 'For You · Word-Level AMLL Karaoke & Phonetics',
    gal1_desc:
      'Syllable-accurate vocal sweep, instant offline Romaji / Pinyin / Korean phonetics via the R hotkey, continuous playlist queue, and smart Collections.',
    gal2_badge: 'New in 6.1',
    gal2_title: 'YouTube Online Hi-Fi Studio — Personal Feed & DPAPI Sync',
    gal2_desc:
      'Automatically loads your YouTube Home feed, Playlists, Liked Videos, Watch Later, and Subscriptions directly from the Windows DPAPI Encrypted Cookie Vault with Dynamic Island Pill & live EQ.',
    gal3_badge: '4K Video · Audio-Only',
    gal3_title: 'YouTube Watch Stage + BoTube AI Subtitles & Radio Mix',
    gal3_desc:
      'Switch seamlessly between 4K GPU Video and 64-bit OPUS Audio-Only. Supports 3 subtitle modes (Off / YouTube CC / ✨ BoTube AI disk-cached), Chapters, floating PiP Mini-Player, and 1-Click Download handoff.',
    gal4_badge: 'Audio Lab',
    gal4_title: 'Hi-Fi Audio Benchmark Lab & Live A/B Audition',
    gal4_desc:
      'Measures both local tracks and live YouTube streams: RTA spectrum, ±180° phase response, 0 dBTP True-Peak, 1 kHz THD+N, and loudness-matched A/B audition.',
    gal5_badge: 'Flexible Workspace',
    gal5_title: 'Studio Settings & 3 Workspace Modes',
    gal5_desc:
      'Run Offline-only, YouTube Online-only, or Both side-by-side. Live Vietnamese ↔ English switching, DAC pinning, Whisper models, and translation settings auto-save immediately.',
    feat_kicker: 'UNIFIED STUDIO ARCHITECTURE',
    feat_heading: 'Every AI media & audiophile tool unified in one desktop player',
    feat_sub:
      'Cleanly isolates Offline Library and YouTube Online while staying lean on CPU/RAM and keeping your data private on Windows.',
    f0_title: 'YouTube Online 4K Hi-Fi & DPAPI Cookie Vault',
    f0_desc:
      'GPU-smooth 4K playback paired with 64-bit WASAPI audio, Audio-Only mode, floating PiP, Dynamic Island Pill, and disk-cached AI subtitles. Cookies encrypt via Windows DPAPI and auto-shred the Downloads file.',
    f1_title: '64-bit Hi-Fi Audio & Self-Recovering WASAPI',
    f1_desc:
      'EBU R128 (−14 LUFS) with 0 dBTP protection, Squiglink/APO Parametric & 10-Band EQ, WASAPI Exclusive DAC output, 4-tier auto-recovery (≤0.5s) on Bluetooth/DAC drops, and Audio Lab A/B.',
    f2_title: 'Whisper AI CUDA & Fast Synced Lyrics',
    f2_desc:
      'Prioritizes verified LRCLIB or sidecar lyrics with sub-second alignment (< 1s), seamlessly falling back to Faster-Whisper (Tiny to Large-v3) on NVIDIA CUDA or CPU across Lyrics and Dialogue/Film modes.',
    f3_title: 'Multi-LLM Translation & Genius Verification',
    f3_desc:
      'Translate offline for free with NLLB-200 or craft poetic lyrics via Google Gemini, OpenAI (GPT-4o / GPT-5), and Anthropic Claude — backed by cue-level verified Genius cross-checking.',
    f4_title: 'Word-Level Karaoke, Phonetics & 60 FPS FX',
    f4_desc:
      'Apple-Music-grade AMLL Sing sweep synced to vocal syllables, instant offline Romaji / Pinyin / Korean Romanization (R key), optical glow, particle trails, and 60 FPS kinetic typography.',
    f5_title: 'NVENC Video Export, Source Downloads & SHA-256 Updater',
    f5_desc:
      'Hardware-accelerated NVIDIA h264_nvenc subtitle burn-in (16:9 / 9:16 / 4K), native-quality yt-dlp downloads, Smart Resume Collections, and one-click SHA-256 verified GitHub Releases updates.',
    new_kicker: 'RELEASE EVOLUTION',
    new_heading: "What's new in BoTube 6.1?",
    new_sub:
      'Existing BoTube 5.0 and 6.0 users simply run the 6.1 BoTube_Setup.exe — Inno Setup upgrades cleanly in-place while preserving 100% of your media library, subtitles, and AI models.',
    table_caption: 'Comparison of capabilities across BoTube 5.0, 6.0, and 6.1',
    th_area: 'Capability',
    r0_k: 'YouTube Online Hi-Fi',
    r0_v5: 'Download-only via yt-dlp',
    r0_v6: 'Source-quality downloads',
    r0_v61: '4K GPU YouTube Studio + 64-bit Hi-Fi audio, cached AI Subtitles, Audio-Only, PiP & Pill Mode',
    r7_k: 'Sync & Security',
    r7_v5: 'No account integration',
    r7_v6: 'Download cookie support',
    r7_v61: 'Windows DPAPI Encrypted Cookie Vault, auto-shred Downloads file, auto-synced Home / Playlists / Liked',
    r1_k: 'Audio & WASAPI',
    r1_v5: 'Basic presets',
    r1_v6: '64-bit Hi-Fi, WASAPI, Audio Lab',
    r1_v61: '4-tier mid-playback WASAPI auto-recovery (≤0.5s) & live Audio Lab measurement on YouTube streams',
    r2_k: 'Subtitles & Karaoke',
    r2_v5: 'Basic cue-level sweep',
    r2_v6: 'Word Karaoke, AMLL, R Phonetics',
    r2_v61: 'BoTube AI Subtitles on YouTube + Whisper-only (no-translate) option & full style sync',
    r3_k: 'Video Export & Modes',
    r3_v5: 'CPU libx264, single layout',
    r3_v6: 'NVIDIA GPU h264_nvenc ⚡',
    r3_v61: 'NVENC GPU + 3 Workspace Modes (Both / Offline Only / YouTube Online Only) tuned for lean RAM/CPU',
    r6_k: 'Settings & Updates',
    r6_v5: 'Manual updates, Vietnamese only',
    r6_v6: 'SHA-256 Auto-Updater, VI ↔ EN',
    r6_v61: 'SHA-256 GitHub Releases Auto-Updater, instant live VI ↔ EN & 100% data-safe upgrades',
    inst_kicker: 'UP AND RUNNING IN 2 MINUTES',
    inst_heading: 'Fresh install or seamless upgrade to 6.1 in 3 steps',
    s1_title: 'Download BoTube_Setup.exe',
    s1_desc:
      'Grab the official Windows installer from GitHub Releases. If BoTube 5.0 or 6.0 is already installed, run the new installer directly — your library, subtitles, and AI models remain untouched.',
    s2_title: 'Pick Workspace & Optional AI Models',
    s2_desc:
      'Hi-Fi playback, YouTube Online 4K, and downloads work right away. Whenever you want local AI transcription, open Settings → Download / Manage Offline AI Models.',
    s3_title: 'Stay Up to Date Automatically',
    s3_desc:
      'BoTube checks GitHub Releases automatically, verifies SHA-256 digests, and installs future updates cleanly in-place with one click.',
    cta_title: 'Ready for BoTube 6.1?',
    cta_desc: 'Free, built for 64-bit Windows 10/11 — Offline Hi-Fi Library & YouTube Online unified in one player.',
    cta_btn_dl: 'Download BoTube 6.1 Now',
    cta_btn_src: 'Browse Source on GitHub',
    footer_copy: 'AI Media Player, Hi-Fi Audio Studio & YouTube Online for Windows · Distributed officially via GitHub Releases.',
  },
};

let activeLang = 'vi';
let latestMeta = null;
let activeLightboxKeys = { titleKey: '', descKey: '' };

function applyLanguage(lang) {
  activeLang = lang === 'en' ? 'en' : 'vi';
  const dict = I18N[activeLang];
  document.documentElement.lang = activeLang;
  document.title = dict._title;

  document.querySelectorAll('[data-i18n]').forEach((el) => {
    const key = el.getAttribute('data-i18n');
    if (key && dict[key]) {
      el.textContent = dict[key];
    }
  });

  document.querySelectorAll('[data-lang-btn]').forEach((btn) => {
    const isSelected = btn.getAttribute('data-lang-btn') === activeLang;
    btn.classList.toggle('is-active', isSelected);
    btn.setAttribute('aria-pressed', String(isSelected));
  });

  if (activeLightboxKeys.titleKey) {
    const lt = document.getElementById('lightbox-title');
    const ld = document.getElementById('lightbox-desc');
    if (lt && dict[activeLightboxKeys.titleKey]) lt.textContent = dict[activeLightboxKeys.titleKey];
    if (ld && dict[activeLightboxKeys.descKey]) ld.textContent = dict[activeLightboxKeys.descKey];
  }

  if (latestMeta) {
    renderLatestReleaseMeta(latestMeta);
  }
  syncDemoButtonLabel();
  try {
    localStorage.setItem('botube_site_lang', activeLang);
  } catch {
    // Ignore restricted storage contexts
  }
}

/* Interactive Stage Tabs */
function initStageTabs() {
  const tabs = Array.from(document.querySelectorAll('[data-stage-tab]'));
  const panels = Array.from(document.querySelectorAll('.stage-panel'));

  function activate(tab) {
    const target = tab.getAttribute('data-stage-tab');
    tabs.forEach((btn) => {
      const selected = btn === tab;
      btn.classList.toggle('is-active', selected);
      btn.setAttribute('aria-selected', String(selected));
    });
    panels.forEach((panel) => {
      const match = panel.id === `panel-${target}`;
      panel.hidden = !match;
      panel.classList.toggle('is-active', match);
    });
    // Pause Karaoke timer unless the AMLL demo tab is actually active
    if (target === 'karaoke' && userWantsDemo && stageVisible) {
      startDemoTimer();
    } else {
      stopDemoTimer();
    }
  }

  tabs.forEach((tab, idx) => {
    tab.addEventListener('click', () => activate(tab));
    tab.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        e.preventDefault();
        const next = tabs[(idx + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
        next.focus();
        activate(next);
      }
    });
  });
}

/* Native <dialog closedby="any"> Screenshot Lightbox with Safari pointer fallback */
function initGalleryLightbox() {
  const dialog = document.getElementById('gallery-lightbox');
  const imgEl = document.getElementById('lightbox-img');
  const titleEl = document.getElementById('lightbox-title');
  const descEl = document.getElementById('lightbox-desc');
  if (!dialog || !imgEl) return;

  function openLightbox(trigger) {
    const src = trigger.getAttribute('data-lightbox-src') || '';
    const titleKey = trigger.getAttribute('data-lightbox-title-key') || '';
    const descKey = trigger.getAttribute('data-lightbox-desc-key') || '';
    const thumb = trigger.querySelector('img');
    const dict = I18N[activeLang];
    activeLightboxKeys = { titleKey, descKey };
    imgEl.src = src;
    imgEl.alt = (thumb && thumb.alt) || (dict[titleKey] || '');
    if (titleEl) titleEl.textContent = dict[titleKey] || '';
    if (descEl) descEl.textContent = dict[descKey] || '';
    if (typeof dialog.showModal === 'function') {
      dialog.showModal();
    }
  }

  document.querySelectorAll('[data-lightbox-src]').forEach((btn) => {
    btn.addEventListener('click', () => openLightbox(btn));
  });

  dialog.addEventListener('close', () => {
    dialog.returnValue = '';
  });

  // Fallback for browsers without native <dialog closedby="any"> support (e.g. Safari)
  if (!('closedBy' in HTMLDialogElement.prototype)) {
    const outside = (e) => {
      const r = dialog.getBoundingClientRect();
      return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
    };
    let pressedOutside = false;
    dialog.addEventListener('pointerdown', (e) => {
      pressedOutside = outside(e);
    });
    dialog.addEventListener('pointerup', (e) => {
      if (pressedOutside && outside(e)) {
        dialog.close();
      }
    });
  }
}

/* Interactive Karaoke + Spectrum Demo with explicit Pause/Play & off-screen background pause */
const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
let userWantsDemo = !prefersReducedMotion;
let stageVisible = true;
let demoTimer = null;
let demoWordIndex = 2;

function isKaraokeTabActive() {
  const panel = document.getElementById('panel-karaoke');
  return Boolean(panel && !panel.hidden);
}

function syncDemoButtonLabel() {
  const btn = document.getElementById('demo-motion-btn');
  if (!btn) return;
  const dict = I18N[activeLang];
  btn.textContent = userWantsDemo ? dict.demo_pause : dict.demo_play;
}

function tickStudioDemo() {
  const words = Array.from(document.querySelectorAll('#demo-lyric-line .word'));
  const bars = Array.from(document.querySelectorAll('#demo-spectrum span'));
  if (!words.length || !bars.length) return;

  demoWordIndex = (demoWordIndex + 1) % words.length;
  words.forEach((w, i) => {
    w.classList.toggle('is-sung', i < demoWordIndex);
    w.classList.toggle('is-active', i === demoWordIndex);
  });

  bars.forEach((bar, i) => {
    const wave = Math.abs(Math.sin(Date.now() / 380 + i * 0.45));
    const centerBoost = 1 - Math.abs(i - bars.length / 2) / (bars.length * 0.65);
    const scale = Math.max(0.14, Math.min(0.98, 0.22 + wave * 0.68 * Math.max(0.35, centerBoost)));
    bar.style.transform = `scaleY(${scale.toFixed(2)})`;
  });
}

function paintStaticSpectrum() {
  const bars = Array.from(document.querySelectorAll('#demo-spectrum span'));
  const pattern = [0.24, 0.38, 0.56, 0.44, 0.72, 0.61, 0.85, 0.74, 0.92, 0.68, 0.88, 0.95, 0.81, 0.76, 0.9, 0.66, 0.79, 0.58, 0.64, 0.48, 0.52, 0.36, 0.3, 0.22];
  bars.forEach((bar, i) => {
    bar.style.transform = `scaleY(${pattern[i % pattern.length]})`;
  });
}

function stopDemoTimer() {
  if (demoTimer) {
    clearInterval(demoTimer);
    demoTimer = null;
  }
}

function startDemoTimer() {
  stopDemoTimer();
  if (!userWantsDemo || !stageVisible || !isKaraokeTabActive()) return;
  tickStudioDemo();
  demoTimer = setInterval(tickStudioDemo, 720);
}

function setDemoRunning(running) {
  userWantsDemo = running;
  if (userWantsDemo) {
    startDemoTimer();
  } else {
    stopDemoTimer();
    paintStaticSpectrum();
  }
  syncDemoButtonLabel();
}

function initDemoBackgroundPause() {
  const canvas = document.querySelector('#panel-karaoke .studio-canvas');
  if (!canvas) return;
  if ('contentVisibility' in document.documentElement.style) {
    canvas.addEventListener('contentvisibilityautostatechange', (event) => {
      stageVisible = !event.skipped;
      if (stageVisible) startDemoTimer();
      else stopDemoTimer();
    });
  } else if ('IntersectionObserver' in window) {
    const obs = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          stageVisible = entry.isIntersecting;
          if (stageVisible) startDemoTimer();
          else stopDemoTimer();
        }
      },
      { rootMargin: '200px' }
    );
    obs.observe(canvas);
  }
}

/* Live GitHub Releases API integration */
function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return '';
  const mb = bytes / (1024 * 1024);
  return `${mb.toFixed(1)} MB`;
}

function renderLatestReleaseMeta(meta) {
  const chip = document.getElementById('nav-version-chip');
  const badge = document.getElementById('hero-release-badge');
  const metaPill = document.getElementById('release-meta-pill');
  const ver = meta.version || DEFAULT_VERSION;
  if (chip) chip.textContent = `v${ver}`;
  if (badge) {
    badge.textContent =
      activeLang === 'en'
        ? `Latest Release v${ver} · Windows 10/11 64-bit`
        : `Bản mới nhất v${ver} · Windows 10/11 64-bit`;
  }
  if (metaPill && meta.sizeLabel) {
    metaPill.textContent = `Windows 10/11 64-bit · ${meta.sizeLabel}`;
  }
  if (meta.downloadUrl) {
    document.querySelectorAll('.js-download-link').forEach((link) => {
      link.setAttribute('href', meta.downloadUrl);
    });
  }
  if (meta.htmlUrl) {
    document.querySelectorAll('.js-release-page-link').forEach((link) => {
      link.setAttribute('href', meta.htmlUrl);
    });
  }
}

async function fetchLatestGitHubRelease() {
  try {
    const resp = await fetch(REPO_API, {
      headers: { Accept: 'application/vnd.github+json' },
    });
    if (!resp.ok) return;
    const data = await resp.json();
    if (!data || data.draft) return;
    const tag = String(data.tag_name || '').replace(/^[vV]/, '') || DEFAULT_VERSION;
    const assets = Array.isArray(data.assets) ? data.assets : [];
    const setupAsset =
      assets.find((a) => String(a.name || '').toLowerCase() === 'botube_setup.exe') ||
      assets.find((a) => String(a.name || '').toLowerCase().endsWith('.exe'));
    latestMeta = {
      version: tag,
      htmlUrl: data.html_url || '',
      downloadUrl: setupAsset ? setupAsset.browser_download_url : '',
      sizeLabel: setupAsset ? formatBytes(Number(setupAsset.size || 0)) : '',
    };
    renderLatestReleaseMeta(latestMeta);
  } catch {
    // Keep clean static v6.1.0 fallback links when offline or rate-limited
  }
}

/* Fallbacks for browsers without native Scroll-Driven Animations */
function initScrollFallbacks() {
  if (prefersReducedMotion) return;

  if (!CSS.supports('animation-timeline', 'scroll()')) {
    const bar = document.getElementById('scroll-progress');
    if (bar) {
      const update = () => {
        const maxScroll = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
        bar.style.transform = `scaleX(${Math.min(1, Math.max(0, window.scrollY / maxScroll))})`;
      };
      window.addEventListener('scroll', update, { passive: true });
      update();
    }
  }

  if (!CSS.supports('(animation-timeline: view()) and (animation-range: entry)')) {
    const cards = Array.from(document.querySelectorAll('.feature-card, .gallery-card, .step-card'));
    if ('IntersectionObserver' in window) {
      const observer = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            if (entry.isIntersecting) {
              entry.target.style.opacity = '1';
              entry.target.style.transform = 'translateY(0)';
              observer.unobserve(entry.target);
            }
          }
        },
        { threshold: 0.12 }
      );
      cards.forEach((card) => {
        card.style.opacity = '0';
        card.style.transform = 'translateY(16px)';
        card.style.transition = 'opacity 0.45s ease, transform 0.45s ease';
        observer.observe(card);
      });
    }
  }
}

document.addEventListener('DOMContentLoaded', () => {
  let savedLang = 'vi';
  try {
    savedLang = localStorage.getItem('botube_site_lang') || 'vi';
  } catch {
    savedLang = 'vi';
  }
  applyLanguage(savedLang);

  document.querySelectorAll('[data-lang-btn]').forEach((btn) => {
    btn.addEventListener('click', () => applyLanguage(btn.getAttribute('data-lang-btn')));
  });

  initStageTabs();
  initGalleryLightbox();
  paintStaticSpectrum();
  initDemoBackgroundPause();

  const demoBtn = document.getElementById('demo-motion-btn');
  if (demoBtn) {
    demoBtn.addEventListener('click', () => setDemoRunning(!userWantsDemo));
  }

  initScrollFallbacks();
  fetchLatestGitHubRelease();
});
