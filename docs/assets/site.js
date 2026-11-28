'use strict';

const REPO_API = 'https://api.github.com/repos/Diablo-Loc/App-AI-media-player/releases/latest';
const DEFAULT_VERSION = '6.0.2';

const I18N = {
  vi: {
    _title: 'BoTube 6.0 — AI Media Player & Hi-Fi Audio Studio',
    skip: 'Chuyển thẳng tới nội dung chính',
    nav_features: 'Tính năng',
    nav_whats_new: 'Điểm mới 6.0',
    nav_install: 'Cài đặt',
    nav_download: 'Tải Windows',
    hero_badge: 'Phiên bản 6.0.2 · Dành cho Windows 10/11 64-bit',
    hero_title: 'Trình phát Media AI & Phòng thu Âm thanh Hi-Fi 64-bit',
    hero_lead:
      'Kết hợp phát nhạc Bit-Pure WASAPI Exclusive, nhận diện lời Whisper AI, dịch đa mô hình LLM, Karaoke khớp từng chữ, phiên âm tức thì và xuất video tăng tốc GPU NVIDIA NVENC — tất cả trong một ứng dụng desktop siêu mượt.',
    hero_dl_btn: 'Tải BoTube_Setup.exe',
    hero_releases_btn: 'Xem bản phát hành',
    pill_platform: 'Windows 10 / 11 64-bit',
    pill_sha: 'Xác thực SHA-256 & Auto-Update',
    pill_upgrade: 'Nâng cấp 5.0 → 6.0 giữ 100% dữ liệu',
    pill_bilingual: 'Song ngữ Việt / Anh tức thì',
    tab_karaoke: 'Karaoke & Hi-Fi',
    tab_ui: 'Giao diện thực tế',
    tab_audio: 'Chuỗi âm thanh',
    demo_sub_vi: 'Giai điệu vang xa vượt qua bầu trời đêm đầy sao',
    demo_pause: 'Tạm dừng mô phỏng',
    demo_play: 'Chạy mô phỏng',
    screenshot_caption:
      'Giao diện Dark Studio thực tế dựng bằng PySide6 / Qt6 với thanh phát nhạc, hàng đợi thông minh và điều khiển phụ đề trực tiếp.',
    chain_title: 'Đường truyền tín hiệu Bit-Pure 64-bit Float',
    chain_1: 'Giải mã chuẩn xác không nén lại (FLAC, WAV, AAC, Opus, MP3)',
    chain_2: 'Chuẩn hóa EBU R128 (−14 LUFS), 10-Band / PEQ Squiglink & chống vỡ đỉnh 0 dBTP',
    chain_3: 'Xuất thẳng tới USB DAC rời, bỏ qua bộ trộn Windows (hỗ trợ Audio Lab A/B)',
    stat_dsp: 'Xử lý âm thanh Float DSP & WASAPI Exclusive',
    stats_heading: 'Thông số nổi bật',
    stat_lyrics: 'Lấy lời nhanh LRCLIB & căn nhịp giọng hát',
    stat_nvenc: 'Xuất video kèm phụ đề tăng tốc phần cứng GPU',
    stat_safe: 'Giữ trọn thư viện, phụ đề & model AI khi cập nhật',
    feat_kicker: 'KIẾN TRÚC PHÒNG THU TOÀN DIỆN',
    feat_heading: 'Mọi công cụ nghe nhìn AI chuyên sâu trong một ứng dụng duy nhất',
    feat_sub:
      'Thiết kế tối ưu tài nguyên CPU/RAM, khởi động tức thì và ưu tiên trải nghiệm cục bộ riêng tư trên Windows.',
    f1_title: 'Âm thanh Hi-Fi 64-bit & Audio Lab',
    f1_desc:
      'Chuẩn hóa âm lượng EBU R128 (−14 LUFS) khử sạch clip vượt trần, 10-Band & Parametric EQ chuẩn Squiglink/APO, hỗ trợ WASAPI Exclusive cho DAC rời và phòng đo phổ RTA đối chiếu A/B trực tiếp.',
    f2_title: 'Whisper AI CUDA & Fast Synced Lyrics',
    f2_desc:
      'Ưu tiên lấy lời chuẩn LRCLIB / sidecar căn nhịp siêu tốc (< 1 giây), tự động chuyển sang Faster-Whisper (Tiny → Large-v3) trên GPU NVIDIA CUDA hoặc CPU với hai chế độ Lời bài hát & Hội thoại/Phim.',
    f3_title: 'Dịch đa mô hình AI & Đối soát Genius',
    f3_desc:
      'Dịch offline miễn phí bằng NLLB-200 hoặc dịch lời nhạc mượt mà qua Google Gemini, OpenAI (GPT-4o / GPT-5) và Anthropic Claude — kết hợp đối chiếu Genius có kiểm định độ khớp từng câu.',
    f4_title: 'Karaoke từng chữ, Phiên âm & Hiệu ứng',
    f4_desc:
      'Hiệu ứng AMLL Sing mượt như Apple Music, khớp từng chữ/âm tiết, tạo dòng phiên âm Romaji / Pinyin / Hàn ngữ hoàn toàn offline (phím tắt R) cùng bộ hiệu ứng hạt và typography chuyên nghiệp.',
    f5_title: 'Xuất Video + Lyric tăng tốc NVENC',
    f5_desc:
      'Gắn phụ đề kèm đầy đủ hiệu ứng quang học vào video với canvas 16:9, 9:16 Shorts, 1:1 hoặc 4K. Tự động tăng tốc phần cứng GPU NVIDIA h264_nvenc, giữ nguyên luồng âm thanh gốc không suy hao.',
    f6_title: 'Cập nhật tự động & Bộ sưu tập thông minh',
    f6_desc:
      'Cập nhật thẳng qua GitHub Releases có kiểm định SHA-256 và tự khởi động lại an toàn. Tích hợp Yêu thích, Playlist tùy biến, Lịch sử phát thông minh (Smart Resume), tải yt-dlp chất lượng gốc và giao diện song ngữ VI/EN.',
    new_kicker: 'BƯỚC NHẢY VỌT PHÁT HÀNH LỚN',
    new_heading: 'Có gì mới từ BoTube 5.0 lên 6.0?',
    new_sub:
      'Máy đang cài BoTube 5.0 chỉ cần chạy BoTube_Setup.exe bản 6.0 — trình cài đặt tự nâng cấp đè sạch sẽ và giữ nguyên 100% dữ liệu.',
    table_caption: 'So sánh cải tiến giữa BoTube 5.0 và BoTube 6.0',
    th_area: 'Hạng mục',
    r1_k: 'Âm thanh & Đo kiểm',
    r1_old: 'Preset cơ bản & cân bằng âm lượng',
    r1_new: 'Hi-Fi 64-bit Float DSP, WASAPI Exclusive DAC, PEQ 10-band & phòng đo Audio Lab A/B',
    r2_k: 'Phụ đề & Karaoke',
    r2_old: 'Quét theo câu, hiệu ứng cơ bản',
    r2_new: 'Karaoke khớp từng chữ thật, AMLL Sing, Phiên âm Romaji/Pinyin/Hàn offline (phím R)',
    r3_k: 'Xuất Video + Lyric',
    r3_old: 'Mã hóa CPU libx264',
    r3_new: 'Tự động tăng tốc phần cứng GPU NVIDIA h264_nvenc ⚡ + fallback CPU mượt mà',
    r4_k: 'Quản lý thư viện',
    r4_old: 'Home, For You, Library',
    r4_new: 'Thêm Bộ sưu tập (Yêu thích / Playlist / Nghe nhiều nhất) & Lịch sử Smart Resume',
    r5_k: 'Cài đặt & Ngôn ngữ',
    r5_old: 'Chỉ Tiếng Việt, lưu thủ công',
    r5_new: 'Studio Settings tự động lưu & chuyển đổi song ngữ 100% Việt ↔ Anh tức thì',
    r6_k: 'Cập nhật & Tối ưu',
    r6_old: 'Cài thủ công, gói đóng gói cồng kềnh',
    r6_new: 'Auto-Updater GitHub Releases + SHA-256 + Inno Setup êm ái, giảm >174 MB gói cài',
    inst_kicker: 'BẮT ĐẦU TRONG 2 PHÚT',
    inst_heading: 'Cài mới hoặc nâng cấp từ 5.0 chỉ với 3 bước',
    s1_title: 'Tải BoTube_Setup.exe',
    s1_desc:
      'Tải bộ cài chính thức từ GitHub Releases. Nếu máy đã cài bản 5.0, chỉ cần chạy trực tiếp bộ cài mới — toàn bộ thư viện, phụ đề và mô hình AI được giữ nguyên 100%.',
    s2_title: 'Chuẩn bị gói AI tùy chọn',
    s2_desc:
      'Nghe nhạc Hi-Fi, tải video và xem phụ đề có sẵn hoạt động ngay lập tức. Khi cần tạo phụ đề tự động, mở Cài đặt → Tải / Cập nhật mô hình AI để tải Whisper / NLLB.',
    s3_title: 'Luôn tự động lên bản mới',
    s3_desc:
      'Từ bản 6.0 trở đi, BoTube tự kiểm tra bản phát hành mới trên GitHub Releases, xác thực SHA-256 và nâng cấp chỉ bằng một cú bấm ngay trong ứng dụng.',
    cta_title: 'Sẵn sàng nâng cấp lên BoTube 6.0?',
    cta_desc: 'Miễn phí, tối ưu cho Windows 10/11 64-bit, bảo vệ tuyệt đối dữ liệu cục bộ của bạn.',
    cta_btn_dl: 'Tải BoTube 6.0 ngay',
    cta_btn_src: 'Xem mã nguồn GitHub',
    footer_copy: 'Trình phát Media AI & Âm thanh Hi-Fi cho Windows · Phát hành chính thức qua GitHub Releases.',
  },
  en: {
    _title: 'BoTube 6.0 — AI Media Player & Hi-Fi Audio Studio for Windows',
    skip: 'Skip to main content',
    nav_features: 'Features',
    nav_whats_new: "What's New 6.0",
    nav_install: 'Install',
    nav_download: 'Download Windows',
    hero_badge: 'Release 6.0.2 · Built for Windows 10/11 64-bit',
    hero_title: 'AI Media Player & 64-bit Hi-Fi Audio Studio',
    hero_lead:
      'Bit-Pure WASAPI Exclusive audio playback, Faster-Whisper CUDA transcription, Multi-LLM lyric translation, syllable-accurate Karaoke, instant offline phonetics, and NVIDIA NVENC video export — unified in one ultra-responsive desktop studio.',
    hero_dl_btn: 'Download BoTube_Setup.exe',
    hero_releases_btn: 'View Releases',
    pill_platform: 'Windows 10 / 11 64-bit',
    pill_sha: 'SHA-256 Verified Auto-Updater',
    pill_upgrade: '5.0 → 6.0 upgrade keeps 100% data',
    pill_bilingual: 'Live Vietnamese / English UI',
    tab_karaoke: 'Karaoke & Hi-Fi',
    tab_ui: 'Real Interface',
    tab_audio: 'Audio Chain',
    demo_sub_vi: 'A melody echoing far across the starlit midnight sky',
    demo_pause: 'Pause simulation',
    demo_play: 'Play simulation',
    screenshot_caption:
      'Authentic PySide6 / Qt6 Dark Studio interface with smart playback bar, queue management, and live subtitle controls.',
    chain_title: 'Bit-Pure 64-bit Float Signal Path',
    chain_1: 'Lossless decoding with zero recompression (FLAC, WAV, AAC, Opus, MP3)',
    chain_2: 'EBU R128 loudness (−14 LUFS), 10-Band / Parametric EQ & 0 dBTP true-peak protection',
    chain_3: 'Direct WASAPI Exclusive output to external USB DACs with live Audio Lab A/B comparison',
    stat_dsp: 'Float Audio DSP & WASAPI Exclusive DAC',
    stats_heading: 'Key Highlights',
    stat_lyrics: 'Instant LRCLIB lyrics & vocal synchronization',
    stat_nvenc: 'Hardware-accelerated subtitle video burn-in',
    stat_safe: 'Library, subtitles & AI models preserved on update',
    feat_kicker: 'UNIFIED STUDIO ARCHITECTURE',
    feat_heading: 'Every AI media & audiophile tool engineered into one desktop player',
    feat_sub:
      'Tuned for lean CPU/RAM usage, instant startup, and local-first privacy on Windows 10 and 11.',
    f1_title: '64-bit Hi-Fi Audio & Audio Lab',
    f1_desc:
      'EBU R128 (−14 LUFS) loudness normalization with zero true-peak clipping, Squiglink/APO Parametric & 10-Band EQ, WASAPI Exclusive USB DAC output, and an interactive RTA spectrum & live A/B audition lab.',
    f2_title: 'Whisper AI CUDA & Fast Synced Lyrics',
    f2_desc:
      'Prioritizes verified LRCLIB or sidecar lyrics with sub-second vocal alignment (< 1s), seamlessly falling back to Faster-Whisper (Tiny to Large-v3) on NVIDIA CUDA or CPU across Lyrics and Dialogue/Film modes.',
    f3_title: 'Multi-LLM Translation & Genius Verification',
    f3_desc:
      'Translate offline for free with NLLB-200 or craft poetic lyrics via Google Gemini, OpenAI (GPT-4o / GPT-5), and Anthropic Claude — backed by cue-level verified Genius lyric cross-checking.',
    f4_title: 'Word-Level Karaoke, Phonetics & Kinetic FX',
    f4_desc:
      'Apple-Music-grade AMLL Sing sweep synced to vocal syllables, instant offline Romaji / Pinyin / Korean Romanization (hotkey R), optical neon glow, particle trails, and kinetic typography.',
    f5_title: 'NVIDIA NVENC Video + Lyrics Export',
    f5_desc:
      'Burn displayed lyrics and optical effects into 16:9, 9:16 Shorts, 1:1, or 4K video with automatic NVIDIA h264_nvenc hardware encoding, seamless CPU fallback, and lossless audio stream copy.',
    f6_title: 'Auto-Updater & Smart Collections',
    f6_desc:
      'One-click in-app updates via GitHub Releases with SHA-256 verification and automatic non-elevated relaunch. Includes Favorites, custom Playlists, Smart Resume History, yt-dlp source-quality downloads, and 100% live VI/EN UI.',
    new_kicker: 'MAJOR RELEASE MILESTONE',
    new_heading: "What's new upgrading from BoTube 5.0 to 6.0?",
    new_sub:
      'Existing BoTube 5.0 users simply run the 6.0 BoTube_Setup.exe — Inno Setup upgrades in-place cleanly while preserving 100% of your media library, subtitles, and offline AI models.',
    table_caption: 'Comparison of major upgrades between BoTube 5.0 and BoTube 6.0',
    th_area: 'Capability',
    r1_k: 'Audio & Measurement',
    r1_old: 'Basic presets & volume normalization',
    r1_new: '64-bit Float Hi-Fi DSP, WASAPI Exclusive DAC, 10-Band / PEQ & Audio Lab A/B benchmark',
    r2_k: 'Subtitles & Karaoke',
    r2_old: 'Cue-level sweep & basic styling',
    r2_new: 'True word-level Karaoke, AMLL Sing, offline Romaji / Pinyin / Korean phonetics (R key)',
    r3_k: 'Video + Lyrics Export',
    r3_old: 'CPU libx264 encoding only',
    r3_new: 'Automatic NVIDIA GPU h264_nvenc ⚡ acceleration with seamless CPU fallback',
    r4_k: 'Library Management',
    r4_old: 'Home, For You, Library',
    r4_new: 'Added Collections (Favorites / Playlists / Most Played) & Smart Resume History',
    r5_k: 'Settings & Language',
    r5_old: 'Vietnamese only, manual save',
    r5_new: 'Auto-saving Studio Settings & 100% live Vietnamese ↔ English switching',
    r6_k: 'Updates & Footprint',
    r6_old: 'Manual downloads, larger runtime bundle',
    r6_new: 'GitHub Releases SHA-256 Auto-Updater, silent Inno Setup & >174 MB leaner package',
    inst_kicker: 'UP AND RUNNING IN 2 MINUTES',
    inst_heading: 'Fresh install or seamless 5.0 → 6.0 upgrade in 3 steps',
    s1_title: 'Download BoTube_Setup.exe',
    s1_desc:
      'Grab the official Windows installer from GitHub Releases. If BoTube 5.0 is already installed, run the new installer directly — your playlists, subtitles, and AI models remain untouched.',
    s2_title: 'Install Optional AI Models',
    s2_desc:
      'Hi-Fi playback, downloads, and existing subtitles work immediately. Whenever you want neural transcription, open Settings → Download / Manage Offline AI Models.',
    s3_title: 'Stay Up to Date Automatically',
    s3_desc:
      'Starting with 6.0, BoTube checks GitHub Releases automatically, verifies SHA-256 digests, and installs future updates in-place with one click.',
    cta_title: 'Ready to upgrade to BoTube 6.0?',
    cta_desc: 'Free, built for 64-bit Windows 10/11, and engineered to keep your local library strictly yours.',
    cta_btn_dl: 'Download BoTube 6.0 Now',
    cta_btn_src: 'Browse Source on GitHub',
    footer_copy: 'AI Media Player & Hi-Fi Audio Studio for Windows · Distributed officially via GitHub Releases.',
  },
};

let activeLang = 'vi';
let latestMeta = null;

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

/* Interactive Karaoke + Spectrum Demo with explicit WCAG Pause/Play control */
const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
let demoPlaying = !prefersReducedMotion;
let demoTimer = null;
let demoWordIndex = 2;

function syncDemoButtonLabel() {
  const btn = document.getElementById('demo-motion-btn');
  if (!btn) return;
  const dict = I18N[activeLang];
  btn.textContent = demoPlaying ? dict.demo_pause : dict.demo_play;
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
    const wave = Math.abs(Math.sin((Date.now() / 380) + i * 0.45));
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

function setDemoRunning(running) {
  demoPlaying = running;
  if (demoTimer) {
    clearInterval(demoTimer);
    demoTimer = null;
  }
  if (demoPlaying) {
    tickStudioDemo();
    demoTimer = setInterval(tickStudioDemo, 720);
  } else {
    paintStaticSpectrum();
  }
  syncDemoButtonLabel();
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
    // Keep clean static v6.0.0 fallback links when offline or rate-limited
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
    const cards = Array.from(document.querySelectorAll('.feature-card, .step-card'));
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

  const demoBtn = document.getElementById('demo-motion-btn');
  if (demoBtn) {
    demoBtn.addEventListener('click', () => setDemoRunning(!demoPlaying));
  }
  setDemoRunning(!prefersReducedMotion);

  initScrollFallbacks();
  fetchLatestGitHubRelease();
});
