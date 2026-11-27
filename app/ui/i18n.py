"""Lightweight, zero-dependency bilingual UI engine (Tiếng Việt / English) for BoTube.

Design guarantees:
1. Persistence separation: Only visual presentation strings (labels, buttons,
   placeholders, tooltips, tab captions, window titles, and `itemData`-backed
   `QComboBox` display texts) are translated. Raw persistence keys and canonical
   QComboBox values ('Local Default', 'Video MP4', 'Original (Best)', 'cuda', etc.)
   are NEVER mutated.
2. Exact reversibility: Before translating any widget property to English, its
   exact original Vietnamese string is stored on the widget (`_i18n_vi_*`), so
   switching English -> Tiếng Việt restores 100% original text verbatim.
3. Zero idle overhead: Current language is cached in RAM (`_CURRENT_LANG`) and
   when set to default `'vi'`, `translate_text` returns immediately in O(1).
"""
from __future__ import annotations

import re
from typing import Callable

from PySide6.QtCore import QEvent, QObject, QSettings, QSignalBlocker, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QDialog,
    QGroupBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QTableView,
    QTabWidget,
    QTextEdit,
    QWidget,
)

SUPPORTED_LANGUAGES: tuple[tuple[str, str], ...] = (
    ('vi', 'Tiếng Việt'),
    ('en', 'English'),
)

_SETTINGS_ORG = 'MyStudio'
_SETTINGS_APP = 'AI_Music_Player'
_SETTINGS_KEY = 'app_language'
_CURRENT_LANG: str | None = None
_LISTENERS: list[Callable[[str], None]] = []


def normalize_language(lang: str | None) -> str:
    val = str(lang or '').strip().lower()
    return 'en' if val.startswith('en') else 'vi'


def get_language() -> str:
    """Return active UI language ('vi' or 'en'), reading QSettings once."""
    global _CURRENT_LANG
    if _CURRENT_LANG is None:
        try:
            s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
            _CURRENT_LANG = normalize_language(s.value(_SETTINGS_KEY, 'vi'))
        except Exception:
            _CURRENT_LANG = 'vi'
    return _CURRENT_LANG


def reload_language_from_settings() -> str:
    """Refresh cached language from current QSettings (useful in isolated tests)."""
    global _CURRENT_LANG
    try:
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        _CURRENT_LANG = normalize_language(s.value(_SETTINGS_KEY, 'vi'))
    except Exception:
        _CURRENT_LANG = 'vi'
    return _CURRENT_LANG


def set_language(lang: str, *, persist: bool = True) -> str:
    """Switch active UI language and notify all live views immediately."""
    global _CURRENT_LANG
    norm = normalize_language(lang)
    changed = _CURRENT_LANG != norm
    _CURRENT_LANG = norm
    if persist:
        try:
            s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
            s.setValue(_SETTINGS_KEY, norm)
        except Exception:
            pass
    if changed or persist:
        for cb in list(_LISTENERS):
            try:
                cb(norm)
            except Exception:
                pass
    return norm


def register_language_listener(callback: Callable[[str], None]) -> None:
    if callback not in _LISTENERS:
        _LISTENERS.append(callback)


def unregister_language_listener(callback: Callable[[str], None]) -> None:
    try:
        _LISTENERS.remove(callback)
    except ValueError:
        pass


def tr_pair(vi_text: str, en_text: str, lang: str | None = None) -> str:
    """Return `en_text` when active language is English, else `vi_text`."""
    use_lang = get_language() if lang is None else normalize_language(lang)
    return en_text if use_lang == 'en' else vi_text


# =====================================================================
# CURATED STUDIO PHRASEBOOK (Exact Vietnamese -> Idiomatic English)
# =====================================================================
VI_TO_EN: dict[str, str] = {
    # --- Main Shell, Sidebar & Toolbar ---
    'Trang chủ': 'Home',
    'For You': 'For You',
    'Thư viện': 'Library',
    'Bộ sưu tập': 'Collections',
    'Lịch sử': 'History',
    'Download': 'Downloads',
    'Tùy chỉnh': 'Settings',
    'Cài đặt': 'Settings',
    '← Tùy chỉnh': '← Settings',
    'Mở/Đóng Menu': 'Toggle Sidebar',
    'Mở thư mục video': 'Open Media Folder',
    'Chọn thư mục video': 'Select Media Folder',
    'Tìm kiếm video...': 'Search videos & music...',
    'Khám phá thư viện': 'Explore Library',
    'Thư viện của bạn': 'Your Library',
    'Video và âm nhạc của bạn, luôn sẵn sàng để phát.': 'Your videos and music, always ready to play.',
    'Đang tải danh sách phát': 'Loading playlist...',

    # --- Playback Bar, Mini Player & AI Strip ---
    'Thêm vào Yêu thích': 'Add to Favorites',
    'Bỏ khỏi Yêu thích': 'Remove from Favorites',
    'Bỏ Yêu thích': 'Remove from Favorites',
    'Yêu thích': 'Favorite',
    'Phát ngẫu nhiên': 'Shuffle',
    'Phát ngẫu nhiên: bật': 'Shuffle: On',
    'Phát ngẫu nhiên: tắt': 'Shuffle: Off',
    'Bài trước': 'Previous Track',
    'Phát / Tạm dừng': 'Play / Pause',
    'Phát': 'Play',
    'Tạm dừng': 'Pause',
    'Bài tiếp theo': 'Next Track',
    'Lặp lại': 'Repeat',
    'Lặp lại: bật': 'Repeat: On',
    'Lặp lại: tắt': 'Repeat: Off',
    'Thêm vào Playlist': 'Add to Playlist',
    'Thông tin bài hát': 'Media Information',
    'Thong tin chi tiết bài hát': 'Detailed Media Information',
    'Cài đặt phụ đề': 'Subtitle & Effects Studio',
    'Công cụ phụ đề': 'Subtitle Editor & Tools',
    'Công cụ khớp & chỉnh sửa phụ đề (Subtitle Tools)': 'Subtitle Sync & Editor Tools',
    'Tạo lại phụ đề': 'Regenerate Subtitles',
    'Tạo lại phụ đề (AI Force)': 'Regenerate Subtitles (Force AI)',
    'Âm lượng': 'Volume',
    'Âm thanh': 'Audio Studio',
    'Mini player': 'Mini Player',
    'Chế độ mini player': 'Dynamic Island Mini Player',
    'Toàn màn hình': 'Fullscreen',
    'Thoát toàn màn hình': 'Exit Fullscreen',
    'Đang chuẩn bị...': 'Preparing AI pipeline...',
    '🤖 Đang khởi động AI phụ đề...': '🤖 Starting subtitle AI engine...',
    '🤖 Đang xử lý phụ đề...': '🤖 Generating & translating subtitles...',
    'Lỗi xử lý AI': 'AI processing error',
    '✕ Hủy': '✕ Cancel',

    # --- For You Page ---
    'Tìm kiếm bài hát...': 'Search in queue...',
    'Đang chờ bài hát...': 'Waiting for track...',
    'Danh sách phát': 'Up Next Queue',
    'Bài hát Yêu thích': 'Favorite Tracks',
    'Nghe nhiều nhất': 'Most Played',
    'Đang tìm kiếm…': 'Searching…',
    'Đang khôi phục danh sách…': 'Restoring queue…',
    'Không thể lọc danh sách. Hãy thử lại.': 'Could not filter queue. Please try again.',

    # --- Collections / Playlists Page & Menus ---
    'BỘ SƯU TẬP': 'COLLECTIONS',
    'Tạo playlist': 'New Playlist',
    'Tạo Playlist': 'Create Playlist',
    'Tạo Playlist mới': 'Create New Playlist',
    'Tạo Playlist cá nhân': 'Create Personal Playlist',
    'Đặt tên cho Playlist mới:': 'Enter a name for your new playlist:',
    'Nhập tên cho Playlist mới của bạn:': 'Enter a name for your new playlist:',
    'VD: Nhạc Học Bài, Ballad Buồn, EDM Tập Gym...': 'e.g. Late Night Chill, Workout Mix, Acoustic...',
    'VD: Nhạc Chill Đêm Khuya, US-UK Hay Nhất...': 'e.g. Late Night Chill, Best Pop Hits...',
    'Tạo & Thêm bài': 'Create & Add Track',
    'Nhập tên mới cho Playlist:': 'Enter a new playlist name:',
    'Lưu tên mới': 'Save Name',
    'Lưu': 'Save',
    'Xác nhận': 'Confirm',
    'Bài hát': 'Tracks',
    'NGUỒN THƯ MỤC': 'MEDIA FOLDERS',
    'Thêm thư mục nhạc/video': 'Add Media Folder',
    'Chọn thêm thư mục nhạc / video': 'Select Media Folder to Add',
    'Quét lại toàn bộ thư mục': 'Rescan All Folders',
    'Phát tất cả': 'Play All',
    'Phát toàn bộ danh sách': 'Play Entire List',
    'Trộn bài': 'Shuffle Play',
    'Phát ngẫu nhiên danh sách': 'Shuffle Entire List',
    'Đặt lại thống kê nghe nhiều nhất': 'Reset Most Played Stats',
    'Đặt lại Top nghe nhiều nhất': 'Reset Most Played Rankings',
    'Đặt lại thống kê': 'Reset Stats',
    'Bạn có chắc chắn muốn đặt lại toàn bộ thống kê lượt nghe và thời gian nghe? Yêu thích, Playlist và Lịch sử xem không bị ảnh hưởng.':
        'Are you sure you want to reset all play counts and listening time? Favorites, Playlists, and History will not be affected.',
    'Thêm bài': 'Add Tracks',
    'Chọn thêm bài từ Thư viện': 'Add Tracks from Library',
    'Đổi tên Playlist': 'Rename Playlist',
    'Xóa Playlist': 'Delete Playlist',
    'Tìm trong danh sách...': 'Filter tracks in list...',
    'TIÊU ĐỀ': 'TITLE',
    'LƯỢT NGHE': 'PLAYS',
    'THỜI LƯỢNG': 'DURATION',
    'TỔNG LƯỢT PHÁT': 'TOTAL PLAYS',
    'THỜI GIAN NGHE': 'LISTENING TIME',
    'NGHỆ SĨ HÀNG ĐẦU': 'TOP ARTIST',
    '0 giây': '0 sec',
    '0 lượt': '0 plays',
    '0 bài hát': '0 tracks',
    'Tất cả thời gian': 'All time',
    '30 ngày qua': 'Last 30 days',
    '7 ngày qua': 'Last 7 days',
    'Tính lượt khi nghe >50% bài': 'Counts plays >50% duration',
    'Thiếu file gốc': 'Missing source file',
    'Danh sách đang trống': 'This list is empty',
    'Chưa thêm thư mục nguồn.': 'No media folders added yet.',
    'Top bài hát nghe nhiều nhất': 'Most Played Tracks',
    'Phát Top': 'Play Top Tracks',
    'Không tìm thấy bài hát phù hợp': 'No matching tracks found',
    'Chưa có dữ liệu': 'No data yet',
    'Chưa có bài hát Yêu thích': 'No Favorite Tracks Yet',
    'Bấm biểu tượng trái tim trên thanh phát nhạc hoặc chuột phải vào video bất kỳ để lưu vào đây.':
        'Click the heart icon on the playback bar or right-click any track to save it here.',
    'Chưa có dữ liệu bảng xếp hạng': 'No Most-Played Rankings Yet',
    'Nghe trên 50% thời lượng bài hát (hoặc 4 phút với video dài) để BoTube ghi nhận 1 lượt nghe vào bảng xếp hạng.':
        'Listen to over 50% of a track (or 4 minutes on long videos) to record a play in your rankings.',
    'Playlist này chưa có bài hát': 'This Playlist Is Empty',
    'Bấm nút “Thêm bài” ở trên hoặc chuột phải vào bài hát bất kỳ ở Thư viện để thêm vào.':
        'Click “Add Tracks” above or right-click any item in your Library to add tracks.',
    'Thêm vào Playlist khác': 'Add to Another Playlist',
    'Gỡ khỏi danh sách': 'Remove from List',
    'Gỡ khỏi Bảng xếp hạng': 'Remove from Rankings',
    'Tạo Playlist mới và thêm bài này...': 'Create New Playlist with This Track...',
    'Tìm nhanh theo tên bài hát hoặc ca sĩ...': 'Quick search by song title or artist...',
    'Chọn tất cả đang lọc': 'Select All Filtered',
    'Phát ngay': 'Play Now',
    'Hiển thị trong thư mục': 'Show in Explorer',
    'ℹ️ Thư mục này đã có trong danh sách nguồn': 'ℹ️ This folder is already in your media sources',
    '🔄 Đã đặt lại bảng xếp hạng nghe nhiều nhất': '🔄 Most Played rankings have been reset',

    # --- History Page ---
    'Xóa khỏi lịch sử': 'Remove from History',
    'Lịch sử xem': 'Playback History',
    '·  Tự động gom theo ngày và dọn gọn lịch sử cũ': '·  Automatically grouped by date with smart retention',
    'Phát toàn bộ lịch sử': 'Play Entire History',
    'Xóa lịch sử': 'Clear History',
    'Xóa toàn bộ lịch sử': 'Clear All Playback History',
    'Xóa toàn bộ lịch sử xem': 'Clear Playback History',
    'Bạn có chắc chắn muốn xóa toàn bộ lịch sử xem? Yêu thích, Playlist và Top nghe nhiều nhất vẫn được giữ nguyên.':
        'Are you sure you want to clear your entire playback history? Favorites, Playlists, and Most Played rankings will remain intact.',
    '🕒 Đã xóa mục khỏi lịch sử xem': '🕒 Removed item from playback history',
    '🧹 Đã xóa sạch toàn bộ lịch sử xem': '🧹 Playback history cleared',
    'TIẾP TỤC PHIÊN NGHE GẦN NHẤT': 'RESUME LAST SESSION',
    'Nghe tiếp': 'Resume',
    'Tiếp tục phát tại vị trí dừng': 'Resume from where you left off',
    'Tìm bài hát, ca sĩ hoặc ngày xem (VD: Hôm nay, 27/11)...': 'Search songs, artists, or dates (e.g. Today, 27/11)...',
    'Lưu giữ:': 'Keep history:',
    '7 ngày gần nhất': 'Last 7 days',
    '14 ngày gần nhất': 'Last 14 days',
    '30 ngày gần nhất': 'Last 30 days',
    '90 ngày gần nhất': 'Last 90 days',
    'Không giới hạn ngày': 'Unlimited days',
    'Tối đa 50 bài': 'Max 50 items',
    'Tối đa 100 bài': 'Max 100 items',
    'Tối đa 200 bài': 'Max 200 items',
    'Tối đa 300 bài': 'Max 300 items',
    'Tối đa 500 bài': 'Max 500 items',
    'Chưa có lịch sử xem': 'No Playback History Yet',
    'Mỗi khi bạn phát một video hoặc bài hát, thời điểm xem sẽ tự động lưu tại đây theo từng ngày.':
        'Whenever you play a video or song, your listening timeline is automatically organized here by day.',
    'Không tìm thấy kết quả phù hợp': 'No matching history entries found',

    # --- Download Page, SettingMenu & Core AI Installer ---
    'Tải video & âm nhạc': 'Video & Music Downloader',
    'Cài đặt chất lượng & Hệ thống': 'Quality & Engine Settings',
    'Cài đặt tải xuống': 'Download Settings',
    'CÀI ĐẶT TẢI XUỐNG': 'DOWNLOAD SETTINGS',
    'Bật: Dùng đường dẫn bên cạnh | Tắt: Lưu tại thư mục video': 'On: Use custom folder | Off: Save to active media folder',
    'Chọn thư mục lưu video...': 'Select download destination...',
    'Chọn thư mục lưu video': 'Select Download Destination',
    'Chọn thư mục lưu': 'Browse Folder',
    'Danh sách link': 'Media URLs',
    'Dán link video hoặc nhạc (mỗi dòng một link)...': 'Paste video or music URLs (one URL per line)...',
    'Tên video': 'Custom Titles',
    "Để trống = Tự lấy tiêu đề gốc khi bấm Bắt đầu,\nhoặc bấm 'Lấy tên' / tự nhập tên từng dòng...":
        "Leave blank = Auto-fetch original titles on Start,\nor click 'Fetch Titles' / enter custom names line by line...",
    'Thành công:': 'Completed:',
    'Thất bại:': 'Failed:',
    'Đã sẵn sàng.': 'Ready to download.',
    'Đã dọn dẹp sẵn sàng.': 'Cleared and ready.',
    'Lấy tên': 'Fetch Titles',
    'Đang lấy...': 'Fetching...',
    'Bắt đầu': 'Start Download',
    'Đang tải...': 'Downloading...',
    'Đang chạy...': 'Running...',
    'Dừng': 'Stop',
    'Xóa trắng': 'Clear',
    'Cập nhật': 'Refresh Library',
    'Chuẩn Hi-Fi': 'Hi-Fi Master',
    'Định dạng:': 'Container:',
    'Chất lượng:': 'Audio / Quality:',
    'Độ phân giải:': 'Max Resolution:',
    'Cookie trình duyệt:': 'Browser Cookies:',
    'Tắt (Mặc định)': 'Off (Default)',
    'Chỉ bật khi tải nhạc YouTube Music Premium hoặc video giới hạn tuổi/chống bot. Tắt mặc định để không đọc dữ liệu trình duyệt.':
        'Enable only for YouTube Music Premium or age/bot-restricted videos. Off by default for browser privacy.',
    'Tự cập nhật Thư viện khi tải xong': 'Auto-refresh Library after download',
    'Tự động cập nhật bộ máy (Luôn bật)': 'Auto-update yt-dlp engine (Always On)',
    'Chế độ: Lưu theo đường dẫn tùy chỉnh.': 'Destination: Saving to custom folder.',
    'Chế độ: Lưu tại thư mục của App.': 'Destination: Saving to active library folder.',
    'Vui lòng chọn hoặc nhập thư mục riêng.': 'Please browse or enter a custom destination folder.',
    'Original (Giữ nguồn)': 'Original (Keep source)',
    'Giữ audio nguồn tốt nhất yt-dlp chọn. MP4 có Opus/VP9/AV1 cần thiết bị hỗ trợ codec.':
        'Preserves the best raw source audio selected by yt-dlp. MP4 with Opus/VP9/AV1 requires codec support.',
    'MKV giữ audio nguồn tốt nhất yt-dlp chọn; không ép Opus hoặc mã hóa lại.':
        'MKV preserves the best raw source audio selected by yt-dlp with zero re-encoding.',
    'Giữ file audio nguồn (ví dụ WebM/Opus hoặc M4A/AAC), không chuyển mã.':
        'Saves the untouched raw audio stream (e.g. WebM/Opus or M4A/AAC) with 0% transcoding.',
    'MP4: chuyển mã audio AAC 128 kbps; video giữ nguồn. Có giảm chất lượng audio.':
        'MP4: transcodes audio to AAC 128 kbps for smaller size while keeping original video.',
    'MP4: ưu tiên AAC gốc, thiếu AAC lấy audio nguồn khác. Không ép bitrate 320k.':
        'MP4: prefers native M4A/AAC stream for universal compatibility without artificial 320k re-encoding.',
    'MP4: ưu tiên Opus gốc, thiếu Opus lấy audio nguồn khác; không chuyển thành AAC.':
        'MP4: prefers native 48 kHz Opus stream without transcoding to AAC.',
    'Chỉ lấy Opus gốc. Nguồn không có Opus: chọn Original; không tự chuyển mã.':
        'Downloads native Opus only (zero transcoding). Switch to Original if source lacks Opus.',
    'Chỉ lấy AAC gốc và đóng gói M4A. Không có AAC: chọn Original.':
        'Downloads native AAC packaged as M4A (zero transcoding). Switch to Original if source lacks AAC.',
    'Tự lưu mức cuối cùng khi chỉnh tại đây, nút loa hoặc phím ↑/↓. Lần đầu: 50%.':
        'Automatically remembers your last volume across sessions (slider, speaker icon, or ↑/↓ keys). Default: 50%.',
    'Chưa phát': 'Idle',
    'Đang đo…': 'Measuring…',
    'Đang đo độ lớn và đỉnh âm thanh…': 'Measuring loudness & true-peak headroom…',
    'Đang chuẩn bị âm thanh chất lượng cao…': 'Preparing 64-bit studio audio stream…',
    'Nguyên gốc': 'Bit-Exact Raw',
    'Đóng': 'Close',
    'Lưu cài đặt': 'Save Settings',
    'Lưu cài đặt tải xuống': 'Save Download Settings',
    'Đặt lại mặc định': 'Reset Defaults',
    'Reset về mặc định': 'Reset Defaults',
    'Hủy': 'Cancel',
    'Trình cài đặt Core AI tự động': 'Offline Core AI Package Manager',
    'CẤU HÌNH HỆ SINH THÁI CORE AI': 'OFFLINE CORE AI MODEL INSTALLER',
    'Ứng dụng tự động thiết lập bộ thư viện dùng chung cho cả CPU & GPU. Vui lòng chọn phiên bản Model:':
        'Automatically configures unified CPU & NVIDIA GPU runtimes. Select a Whisper model package:',
    'Chế độ kiểm thử:': 'Runtime Mode:',
    'Cài đặt bộ thư viện lai (Hỗ trợ cả CPU & GPU NVidia)': 'Hybrid Runtime (Supports both CPU & NVIDIA CUDA GPU)',
    'Phiên bản Model:': 'Whisper Package:',
    'Tải kèm Model dịch thuật NLLB Offline (Facebook ~1.2GB để dịch không cần mạng)':
        'Include Offline NLLB-200 Translation Model (~1.2 GB for 100% offline lyric translation)',
    'Xóa sạch tài nguyên cũ cài lại từ đầu (Khuyên dùng nếu đã dính lỗi mạng cũ)':
        'Clean reinstall from scratch (recommended if a previous download was interrupted)',
    'Bắt đầu cài đặt tự động': 'Start Automated Installation',
    '🟢 Core AI: Đã cài đặt': '🟢 Core AI Runtime: Installed',
    '🔴 Core AI: Chưa cài': '🔴 Core AI Runtime: Not Installed',
    '🟢 Dịch Offline: Đã tải': '🟢 Offline Translator: Installed',
    '⚪ Dịch Offline: Chưa tải': '⚪ Offline Translator: Not Installed',

    # --- Audio Effects Popup & Equalizer ---
    'Chế độ': 'Preset',
    'Thiết bị': 'Device',
    'Âm sắc': 'Voicing',
    'Đầu ra': 'Output',
    'Lấy mẫu': 'Upsample',
    'Pha DAC': 'DAC Phase',
    'Nhạc nén': 'Restorer',
    'Nguyên bản': 'Bit-Pure Original',
    'Chuẩn Hi-Fi (Hợp nhất)': 'Hi-Fi Master (Unified)',
    'Chuẩn Hi-Fi · Hợp nhất': 'Hi-Fi Master · Unified',
    'DAC Rời · Bit-Perfect': 'External DAC · Bit-Perfect',
    'Sống động': 'Walkman Vivid',
    'Tắt (Bypass)': 'Bypass (Raw)',
    'Tắt': 'Off',
    'Tự động': 'Auto',
    'Tự nhiên': 'Natural',
    'Nhẹ': 'Gentle',
    'Rõ nét': 'Crisp',
    'Aria 2 · Phòng thu': 'Aria 2 · Studio Reference',
    'Loa kiểm âm 30°': '30° Studio Crossfeed',
    'Aria 2 · Cân bằng': 'Aria 2 · Balanced',
    'Rõ giọng hát': 'Vocal Presence',
    'Ấm mượt': 'Warm & Smooth',
    'Dịu nhẹ': 'Soft & Relaxed',
    'Cân bằng': 'Balanced',
    'Dễ nghe (Loa)': 'Speaker Comfort',
    'Dễ nghe (Tai nghe)': 'Headphone Comfort',
    'Chia sẻ (Shared)': 'WASAPI Shared',
    'Độc quyền (Exclusive)': 'WASAPI Exclusive',
    'Tần số gốc': 'Native Sample Rate',
    'Tuyến tính (Linear)': 'Linear Phase',
    'Tối thiểu (Minimum)': 'Minimum Phase',
    '−16 LUFS (Chuẩn)': '−16 LUFS (Standard)',
    '−14 LUFS (To rõ)': '−14 LUFS (Vibrant)',
    '−18 LUFS (Tự nhiên)': '−18 LUFS (Audiophile)',
    'Cấu hình khuyên dùng': 'Recommended Hi-Fi Master',
    'Tắt xử lý (âm thanh gốc)': 'Bypass DSP (Bit-exact source)',
    'Mặc định hệ thống': 'System Default Output',
    'Chọn nhanh cấu hình nghe.\nMẹo YouTube: ở trang Tải xuống chọn Original hoặc Opus để giữ nguyên luồng âm thanh.':
        'Quickly switch listening profiles.\nTip: Choose Original or Opus in Downloads to preserve raw source audio.',
    'Chọn trực tiếp USB DAC (như Dawn Pro 2) để phát độc lập với âm thanh hệ thống.':
        'Route directly to your USB DAC (e.g. Dawn Pro 2) independently of Windows system audio.',
    'Mở Equalizer 10 dải, Preamp và Crossfeed.': 'Open 64-bit 10-Band / Parametric Equalizer, Preamp, and Crossfeed.',
    'Shared: nghe chung với ứng dụng khác. Exclusive: đi thẳng vào USB DAC bỏ qua bộ trộn Windows.':
        'Shared: mixes with other apps. Exclusive: bit-exact hardware path bypassing the Windows mixer.',
    'Nâng mẫu SoXR 33-bit đồng bộ khi dùng WASAPI Exclusive trên USB DAC.':
        'Synchronous 33-bit SoXR upsampling when running WASAPI Exclusive on a USB DAC.',
    'Tuyến tính: SoXR 33-bit không xoay pha. Tối thiểu: lọc trễ pha cực tiểu loại bỏ hoàn toàn pre-ringing khi nâng mẫu.':
        'Linear: zero phase shift 33-bit SoXR. Minimum: eliminates pre-ringing on transient attacks.',
    'Bật cân bằng âm lượng tự động theo chuẩn LUFS.': 'Enable automatic ITU-R BS.1770-4 LUFS loudness normalization.',
    'Bù dải cao dịu nhẹ cho nhạc MP3/AAC cũ; tự bỏ qua Opus và Lossless.':
        'Gentle high-frequency restoration for legacy MP3/AAC; automatically bypasses Opus and Lossless.',
    'Tự chuyển cấu hình & EQ khi cắm DAC hoặc đổi tai nghe/loa.':
        'Automatically switch DSP profile & EQ when plugging in a DAC or changing headphones/speakers.',
    'Đo nhanh LUFS bài tiếp theo trong RAM để chuyển bài tức thì.':
        'Pre-scan next track LUFS in RAM for zero-gap track transitions.',
    'Mở tab đo phổ tần số và so sánh file gốc với cấu hình hiện tại.':
        'Open the acoustic spectrum analyzer & gain-matched A/B audition lab.',
    'Tùy chọn nâng cao  ▾': 'Advanced DSP Options  ▾',
    'Tùy chọn nâng cao  ▴': 'Advanced DSP Options  ▴',
    'Nhớ riêng từng thiết bị': 'Remember per output device',
    'Đo trước bài kế tiếp': 'Pre-analyze next track in RAM',
    'Đo kiểm chất âm…': 'Audio Lab Benchmark…',
    'Equalizer  ·  Đang bật': 'Equalizer  ·  Active',
    'Equalizer · Đang bật': 'Equalizer · Active',
    'Bật': 'Enable',
    '10 dải': '10-Band',
    'Lưu mẫu mới': 'Save Preset',
    'Lưu mẫu EQ': 'Save EQ Preset',
    'Tên mẫu:': 'Preset name:',
    'Xóa mẫu đang chọn': 'Delete Preset',
    'Nhấn giữ để so sánh với âm gốc': 'Hold to A/B compare with raw audio',
    'Đang nghe âm gốc': 'Bypassing EQ (Raw)',
    'Đặt lại 0 dB': 'Flatten (0 dB)',
    'Đã đặt lại 0 dB': 'Reset to 0 dB',
    'Nhập / Xuất Equalizer APO': 'Import / Export Equalizer APO',
    'Mở .txt…': 'Import .txt…',
    'Mở file .txt…': 'Import .txt file…',
    'Lưu .txt…': 'Export .txt…',
    'Lưu file .txt…': 'Export .txt file…',
    'Dán APO': 'Paste APO',
    'Dán từ Clipboard': 'Paste from Clipboard',
    'Chép APO': 'Copy APO',
    'Đã chép APO': 'Copied APO',
    'Chép vào Clipboard': 'Copy to Clipboard',
    '+ Thêm dải': '+ Add Band',
    'Xóa PEQ': 'Clear PEQ',
    'Tự giảm Preamp': 'Auto Preamp Guard',
    'Tự giảm mức đầu vào theo đỉnh cộng hưởng để không vỡ tiếng.':
        'Automatically attenuates preamp headroom to prevent EQ peak clipping.',
    'Nhấp đúp hoặc chuột phải để về 0': 'Double-click or right-click to reset to 0',
    'Parametric EQ chuẩn Squiglink / Oratory1990 (Fc + Q + PK/LS/HS)':
        'Squiglink / Oratory1990 Parametric EQ (Fc + Q + PK/LS/HS)',
    'Trầm': 'Bass',
    'Âm trường': 'Soundstage',
    'Crossfeed loa kiểm âm 30°': '30° Studio Monitor Crossfeed',
    'Khử chói Sibilance (PEQ)': 'De-Esser / Sibilance Control (PEQ)',
    'Phẳng': 'Flat (0 dB)',
    'Tăng trầm': 'Bass Boost',
    'Giảm trầm': 'Bass Cut',
    'Jazz & Cổ điển': 'Jazz & Classical',
    'Ấm áp': 'Warm Analog',
    'Tăng sáng': 'Treble Air',
    'Gốc': 'Raw',

    # --- Audio Benchmark Lab Page ---
    'Phân tích âm thanh': 'Audio Signal Lab',
    'Cấu hình đang dùng': 'Active Studio Profile',
    'Bài đang phát': 'Current Track',
    'Chọn file…': 'Choose File…',
    'Chọn file âm thanh': 'Choose media file to analyze',
    'Chọn file nhạc hoặc video để đo kiểm': 'Select Music or Video File to Analyze',
    'Chép báo cáo đo kiểm': 'Copy Benchmark Report',
    'Đo kiểm': 'Run Analysis',
    'Chạy đo kiểm': 'Run acoustic benchmark',
    'Chưa chọn nguồn để đo kiểm.': 'No media source selected for analysis.',
    'Chưa có file hợp lệ. Bấm Chọn file… để kiểm tra.': 'No valid file selected. Click Choose File… to analyze.',
    'Chọn nguồn âm thanh rồi bấm Đo kiểm.': 'Select a track and click Run Analysis.',
    'CHỜ ĐO KIỂM': 'READY',
    'CHỜ ĐO': 'READY',
    'XONG': 'DONE',
    'LỖI': 'ERROR',
    'Chọn bài nhạc rồi bấm Đo kiểm để biết ngay bản sau xử lý đang sạch hơn hay kém hơn bản gốc.':
        'Select a track and click Run Analysis to compare post-DSP clarity, headroom, and dynamics against the raw file.',
    'Chọn bài hát và cấu hình rồi bấm Đo kiểm.': 'Select a track and studio profile, then click Run Analysis.',
    'Chưa có dữ liệu đo.': 'Awaiting measurement.',
    'Độ trong trẻo': 'Clarity & Headroom',
    'Độ nảy & Chi tiết': 'Dynamics & Detail',
    'Màu âm & Không gian': 'Tonality & Soundstage',
    'Nghe thử A/B': 'A/B Audition',
    'Dừng nghe': 'Stop Audition',
    'Đang chuẩn bị…': 'Preparing…',
    'Nghe đối chiếu A/B': 'Level-matched live A/B audition',
    'Dừng nghe thử A/B': 'Stop A/B audition',
    'A · Bản gốc': 'A · Raw Source',
    'B · Sau xử lý': 'B · Processed',
    'Khớp bằng âm lượng': 'Loudness Match',
    'Tự cân độ to hai bản về ngang nhau để tai không bị đánh lừa rằng to hơn là hay hơn.':
        'Automatically loudness-matches A and B so perceived volume differences never bias your ears.',
    'Nghe trực tiếp hai bản ở cùng một độ to để tự cảm nhận bằng tai.':
        'Compare Raw (A) vs Processed (B) at identical perceived loudness in zero-disk RAM.',
    'Bấm "Nghe thử A/B" để nghe cùng một độ to giữa Bản gốc (A) và Sau xử lý (B).':
        'Click "A/B Audition" to compare Raw Source (A) vs Processed (B) at matched loudness.',
    'Đang dựng luồng nghe thử A/B trong RAM (0 MB ổ cứng)…':
        'Rendering sample-aligned A/B audition buffers in RAM (0 MB disk usage)…',
    'Phổ tần số RTA': 'RTA Spectrum',
    'Đáp tuyến · Pha': 'Magnitude · Phase',
    'Đỉnh True-Peak': '4× True-Peak',
    'Phổ 1 kHz THD+N': '1 kHz THD+N',
    'Sau xử lý': 'Processed',
    'Khớp mức LUFS': 'LUFS-Matched',
    'Căn thẳng mức dải giữa để đối chiếu âm sắc khi bật cân bằng âm lượng.':
        'Aligns midrange reference level so tonal differences are clear when loudness normalization is active.',
    'Chuẩn đo: ITU-R BS.1770-4 · AES17 · 4× True-Peak': 'Standards: ITU-R BS.1770-4 · AES17 · 4× Oversampled True-Peak',
    'Thông số đối chiếu chuẩn ITU-R / AES17 (Gốc vs Sau xử lý)':
        'Objective ITU-R / AES17 Measurements (Raw Pre vs Processed Post)',
    'Thông số': 'Parameter',
    'Gốc (Pre)': 'Raw (Pre)',
    'Sau xử lý (Post)': 'Processed (Post)',
    'Đánh giá': 'Status',
    'Trần 0 dBTP': '0 dBTP Ceiling',
    'Đỉnh gốc (Pre)': 'Raw Peak (Pre)',
    'Gốc (0 dB)': 'Raw Ref (0 dB)',
    'Biên độ |H(f)|': 'Magnitude |H(f)|',
    'Pha ∠H(f)': 'Phase ∠H(f)',
    # Benchmark verdicts & pillars
    'SẠCH HƠN BẢN GỐC': 'CLEANER THAN SOURCE',
    'SẠCH ĐỈNH HƠN · ĐÃ CHỈNH GU ÂM': 'CLEANER PEAKS · CUSTOM VOICING',
    'TRUNG THỰC NHƯ GỐC': 'BIT-FAITHFUL TO SOURCE',
    'SẠCH NHƯ GỐC · ĐỔI MÀU ÂM THEO GU': 'CLEAN AS SOURCE · TONAL SHAPING',
    'GIỮ NGUYÊN BẢN GỐC': '1:1 RAW BYPASS',
    'ĐANG PHÁT GỐC · CÓ VỠ ĐỈNH': 'RAW BYPASS · CLIPPING DETECTED',
    'ĐANG PHÁT GỐC · CAO TRÀO VƯỢT TRẦN': 'RAW BYPASS · HOT CLIMAX PEAKS',
    'KÉM HƠN GỐC · BỊ VỠ TIẾNG': 'POST CLIPPING DETECTED',
    'CHỈNH QUÁ ĐÀ · DỄ LỆCH TIẾNG': 'HEAVY EQ DEVIATION',
    'CẦN ĐIỀU CHỈNH LẠI': 'NEEDS ADJUSTMENT',
    'NGUYÊN GỐC (BYPASS)': 'RAW BYPASS (1:1)',
    'CẦN LƯU Ý': 'ATTENTION NEEDED',
    'ĐẠT CHUẨN BIT-PURE': 'BIT-PURE CERTIFIED',
    'CHUẨN HI-RES STUDIO': 'HI-RES STUDIO GRADE',
    'CHUẨN YOUTUBE (−14 LUFS)': 'YOUTUBE LOUDNESS (−14 LUFS)',
    'ĐẠT CHUẨN EBU R128': 'EBU R128 COMPLIANT',
    'Dễ rè nhẹ': 'Prone to Clipping',
    'Dễ rè cao trào': 'Hot Climax Peaks',
    'Sạch như gốc': 'Clean as Source',
    'Kém hơn gốc': 'Clipping Added',
    'Tốt hơn gốc': 'Cleaner than Raw',
    'Giữ nguyên 100%': '100% Preserved',
    'Hụt độ nảy': 'Reduced Dynamics',
    'Nguyên bản 1:1': '1:1 Bit-Transparent',
    'Tinh chỉnh hài hòa': 'Balanced Voicing',
    'Đổi màu âm mạnh': 'Strong EQ Shaping',
    'Kéo EQ quá tay': 'Excessive EQ Boost',
    'Phát thẳng nguyên bản, không có điểm vỡ đỉnh.': 'Bit-direct playback with zero inter-sample clipping.',
    'Đã hạ đỉnh về vùng an toàn cho DAC.': 'Lowered true peaks into safe DAC headroom.',
    'Không phát sinh vỡ tiếng hay méo nền.': 'Zero added clipping or noise-floor distortion.',
    'Không nén động, giữ nguyên nhịp nảy gốc.': 'Zero dynamic compression; micro-transients fully intact.',
    'Không đổi chất giọng hay màu nhạc cụ gốc.': 'Zero coloration to original vocals or instruments.',
    'Đang phát nguyên gốc 100%, không thay đổi âm lượng hay màu âm.':
        '100% bit-exact raw output with zero loudness or tonal modification.',
    'Đầu ra đi thẳng 1:1 không qua chuỗi xử lý 64-bit.': 'Direct 1:1 raw output bypassing the 64-bit DSP chain.',
    'Có điểm cần điều chỉnh ở mức đỉnh hoặc biên độ EQ.': 'Peak headroom or EQ gain requires attention.',
    'Độ động hoặc độ méo đang kém hơn bản gốc, nên chuyển về cấu hình khuyên dùng.':
        'Dynamic range or distortion degraded; switch back to Recommended Hi-Fi Master.',
    'Sạch đỉnh hơn bản gốc: Đã tạo khoảng trống an toàn chống méo DAC, giữ nguyên 100% chất âm gốc.':
        'Cleaner peaks than source: created safe DAC inter-sample headroom while preserving 100% source timbre.',
    'Bản gốc vốn đã rất sạch; chế độ hiện tại giữ nguyên 100% chi tiết gốc và truyền thẳng ra DAC rời.':
        'Source is already clean; active mode preserves 100% detail over bit-exact Exclusive DAC output.',
    'Bản gốc vốn đã sạch; chế độ hiện tại giữ nguyên 100% âm sắc gốc và cân bằng âm lượng êm tai giữa các bài.':
        'Source is already clean; active mode preserves 100% original timbre with smooth track-to-track loudness.',
    'Độ lớn tích hợp (BS.1770-4)': 'Integrated Loudness (BS.1770-4)',
    'Đỉnh thực (4× True-Peak)': '4× Oversampled True-Peak',
    'Mẫu vượt trần (ISP > 0 dBTP)': 'Inter-Sample Clips (ISP > 0 dBTP)',
    'Tỷ lệ Đỉnh / Độ lớn (PLR · DR)': 'Peak-to-Loudness (PLR · Crest DR)',
    'Đáp tuyến (20 Hz – 20 kHz)': 'Frequency Response (20 Hz – 20 kHz)',
    'Tương quan pha Stereo (L/R)': 'Stereo Phase Correlation (L/R)',
    'Tách kênh Stereo (@ 1 kHz)': 'Stereo Crosstalk (@ 1 kHz)',
    'Méo hài & IMD chuỗi DSP': 'DSP Chain THD+N & IMD',
    '0.00 dB (Phẳng)': '0.00 dB (Flat)',
    'Không đổi': 'Unchanged',
    'Quá ngưỡng (> 0 dBTP)': 'Over Ceiling (> 0 dBTP)',
    'Đạt ≤ -1.0 dBTP': 'Optimal (≤ -1.0 dBTP)',
    'An toàn (< 0 dBTP)': 'Safe (< 0 dBTP)',
    'Sạch clip': '0 Clips (Clean)',
    'Biên độ lớn': 'Wide EQ Swing',
    'Theo EQ': 'Shaped (EQ)',
    'Giữ nguyên trường âm': 'Intact Soundstage',
    'Độc lập L/R': 'Isolated L/R',
    'Tuyến tính': 'Ultra-Linear',
    'Đạt chuẩn': 'Transparent',
    'Méo cao': 'High THD',
    'Kiểm soát đỉnh phát': 'True-Peak Headroom',
    'Độ động & Âm sắc': 'Dynamics & Tonality',
    'Phổ nguồn file gốc': 'Source Spectral Bandwidth',
    'Quá ngưỡng đỉnh DAC': 'DAC Peak Overload',
    'Chuẩn hóa đỉnh EBU R128': 'EBU R128 True-Peak Protection',
    'Dự phòng đỉnh DAC an toàn': 'Safe DAC Headroom',
    'Độ động (PLR · Crest DR)': 'Micro-Dynamics (PLR · Crest DR)',
    'Độ trung thực & Băng thông': 'Signal Fidelity & Bandwidth',
    'Độ lệch đáp tuyến lớn': 'Large EQ Magnitude Deviation',
    'Định hình EQ & Băng thông': 'EQ Shaping & Bandwidth',

    # --- Subtitle & Effects Studio Popup (sub_panel.py, subtitle_effects*.py, subtitle_studio.py) ---
    'Phụ đề & Hiệu ứng': 'Subtitles & Studio Effects',
    'Hiệu ứng: Tắt': 'Effects: Off',
    'Khôi phục toàn bộ cài đặt phụ đề về mặc định': 'Restore all subtitle appearance & effect settings to defaults',
    'Hiển thị & Kiểu chữ': 'Display & Typography',
    'Chế độ ngôn ngữ': 'Subtitle Track Mode',
    'Chỉ Lời Gốc (Original)': 'Original Track Only',
    'Chỉ Tiếng Anh (EN)': 'English Only (EN)',
    'Chỉ Tiếng Việt (VI)': 'Vietnamese Only (VI)',
    'Lời Gốc + Anh': 'Original + English',
    'Lời Gốc + Việt': 'Original + Vietnamese',
    'Anh + Việt': 'English + Vietnamese',
    'Tất cả (Gốc + Anh + Việt)': 'All Tracks (Orig + EN + VI)',
    'Tắt phụ đề': 'Subtitles Off',
    '0% (Trong suốt)': '0% (Transparent)',
    '15% (Kính rất nhẹ)': '15% (Ultra-Light Glass)',
    '25% (Nhẹ)': '25% (Light)',
    '35% (Kính dịu)': '35% (Soft Glass)',
    '50% (Chuẩn)': '50% (Balanced)',
    '65% (Rạp tối)': '65% (Cinema Dark)',
    '75% (Đậm)': '75% (Deep)',
    '100% (Đặc)': '100% (Solid)',
    'Trắng chuẩn điện ảnh': 'Cinema Pure White',
    'Vàng dịu rạp hát': 'Theater Warm Yellow',
    'Xanh băng Studio': 'Studio Ice Cyan',
    'Ngọc lam dịu': 'Soft Mint',
    'Hồng Neon nổi bật': 'Vibrant Neon Pink',
    'Kéo để chỉnh cỡ chữ': 'Drag to adjust font size',
    'Màu': 'Color',
    'Chọn màu chữ tùy ý': 'Pick custom text color',
    'Chọn màu chữ': 'Select Subtitle Text Color',
    'Chọn màu viền': 'Select Outline Color',
    'Chọn màu': 'Select Color',
    'Màu nhanh:': 'Quick swatches:',
    'Nền': 'Box',
    'Chọn màu nền': 'Pick background pill color',
    'Viền': 'Outline',
    'Bóng': 'Shadow',
    'Khóa vị trí sub': 'Lock position',
    'Mờ dần (Fade)': 'Smooth Fade',
    '🎤 Chế độ Karaoke': '🎤 Karaoke Mode',
    'Bật chế độ Karaoke sân khấu: phóng to phụ đề, đổi màu sáng chữ theo từng từ thật (Anh/Việt/Nhật/Trung/Hàn + Romaji) và tô vàng ★ các hiệu ứng khuyên dùng':
        'Stage Karaoke Mode: enlarges lyrics, sweeps word-by-word vocal timing (EN/VI/JA/ZH/KO + Romaji), and highlights ★ recommended effects',
    'Phiên âm (R)': 'Phonetics (R)',
    'Hiện dòng phiên âm Latinh (Romaji Nhật / Pinyin Trung / Hangul Hàn) màu xanh băng ở trên cùng (Phím tắt khi xem video: R)':
        'Show top-line Latin phonetics (Japanese Romaji / Chinese Pinyin / Korean Hangul) in ice-cyan (Video shortcut: R)',
    'Cỡ chữ & Màu chữ': 'Font Size & Color',
    'Hộp nền & Độ mờ': 'Background Pill & Opacity',
    'Viền & Bóng quang học': 'Optical Outline & Shadow',
    'Tốc độ phát': 'Playback Speed',
    'Hiệu ứng phụ đề & Xem thử': 'Subtitle Effects & Live Preview',
    'Hiệu ứng phụ đề && Xem thử': 'Subtitle Effects && Live Preview',
    'Bộ mẫu nhanh': 'Effect Preset',
    'Chuyển động câu': 'Cue Entrance',
    'Chuyển động vào và thoát câu mượt 60 FPS.': 'Smooth 60 FPS cue entrance and exit choreography.',
    'Màu sắc & Ánh kim': 'Color & Sheen',
    'Hiệu ứng dọc câu': 'Along-Cue Sweep',
    'Đồng bộ theo tiến độ câu đang hát.': 'Synchronized with active lyric progression.',
    'Mật độ hạt': 'Particle Density',
    'Nhẹ 8 / Vừa 16 / Rực rỡ 24 hạt tối đa.': 'Light (8) / Balanced (16) / Vivid (24) max particles.',
    'Tốc độ hiệu ứng': 'Motion Speed',
    'Tự rút ngắn với câu ngắn; không làm lệch mốc hiển thị sub.':
        'Adapts automatically on short cues without shifting subtitle timestamps.',
    'Lực typography': 'Kinetic Force',
    'Áp dụng cho nhóm hiệu ứng typography.': 'Applies to kinetic typography entrances.',
    'Chia cụm chữ': 'Tile Grouping',
    'Tối đa 16 cụm; giữ nguyên dấu tiếng Việt, Nhật và emoji.':
        'Up to 16 tiles; preserves Vietnamese diacritics, CJK, and emoji.',
    'Ẩn chữ sau vệt quét': 'Hide swept words',
    'Từ đã quét sẽ ẩn tới hết câu; sang câu mới hoặc tua lại hiện bình thường.':
        'Swept words fade away until cue end; seeking or next cue restores visibility.',
    'Mờ dần khi vào câu': 'Soft entry fade',
    'Mờ nhẹ phần chữ khi vào câu.': 'Gentle opacity ease-in at cue start.',
    'Ánh sáng viền quang học': 'Optical Neon Glow',
    'Dải sáng lướt một lần': 'Single Shimmer Sweep',
    'Xem thử hiệu ứng': 'Preview Effect',
    'Xem thử hiệu ứng trực tiếp, không ảnh hưởng video đang phát.': 'Live preview inside popup without affecting video playback.',
    'Rất nhanh · 220 ms': 'Snappy · 220 ms',
    'Vừa · 320 ms': 'Balanced · 320 ms',
    'Êm · 360 ms': 'Smooth · 360 ms',
    'Điện ảnh · 440 ms': 'Cinematic · 440 ms',
    'Mềm · 480 ms': 'Fluid · 480 ms',
    'Hoành tráng · 540 ms': 'Epic · 540 ms',
    # Studio Quick Profiles (labels + tooltips)
    'Nhịp Từng Chữ': 'Beat Per Letter',
    'Xoáy Từng Chữ': 'Orbit Snap',
    'Mưa Từng Chữ': 'Letter Cascade',
    'Bung Tung Tóe': 'Scatter Leap',
    'Siêu Tân Tinh': 'Supernova',
    'Nhất Kiếm Sét': 'Saber Slash',
    'Đập Bass 3D': '3D Bass Drop',
    'Hố Đen': 'Black Hole',
    'Nảy CapCut': 'CapCut Bounce',
    'Hỏa Diễm': 'Phoenix Flame',
    'Lật 3D': '3D Card Flip',
    'Điện Ảnh': 'Cinema Focus',
    'Từ Tính Ghép': 'Magnet Snap',
    'Cơn Lốc Cuốn': 'Cyclone Sweep',
    'Pháo Hoa Rơi': 'Starburst',
    'Gương Vỡ 3D': '3D Glass Shatter',
    'Từng ký tự bay từ nhiều hướng, xoay & nảy vào câu theo nhịp beat rồi lần lượt bắn ra khi đổi câu':
        'Characters fly in from multiple angles, bounce on the beat, and burst outward on cue transition',
    'Từng ký tự xoay theo quỹ đạo rồi khóa sắc nét vào vị trí kèm pháo sao 4 cánh':
        'Characters spiral along an orbit and lock crisply into place with 4-point star sparkles',
    'Từng ký tự rơi lần lượt từ trên xuống nảy đàn hồi rồi bật tung khi chuyển câu':
        'Characters cascade from above with elastic bounce and scatter cleanly on cue change',
    'Câu cũ nổ vỡ bay tung tóe tứ phía, câu mới bật nhảy đàn hồi vào đúng vị trí':
        'Previous cue shatters outward while the new cue leaps elastically into alignment',
    'Bung mảnh 360° kèm sóng xung kích và mưa sao băng': '360° shockwave shatter with supernova meteor embers',
    'Chém xéo ánh thép tách câu kèm chuỗi sét phân nhánh': 'Diagonal steel blade slash with branching lightning arcs',
    'Đập nhịp rung chấn RGB kèm thanh sóng nhạc Equalizer': 'RGB bass-impact shockwave with live equalizer bars',
    'Xé dải nhiễu RGB kèm tia Laser quét dọc từng dòng': 'Cyberpunk RGB split glitch with horizontal laser scanline',
    'Hút xoáy vào chân trời sự kiện và bung quỹ đạo tinh vân': 'Gravitational singularity warp with nebula star orbit',
    'Tan mờ quang học mượt kèm lướt chữ karaoke và nâng nhẹ từng từ':
        'Apple Music optical blur-in with silk word-by-word karaoke sweep and lift',
    'Bật nảy co giãn đàn hồi kèm pháo sao 4 cánh': 'Elastic CapCut spring bounce with 4-point star confetti',
    'Sóng lửa rực kèm tàn lửa bay ngược': 'Blazing liquid fire wave with rising phoenix embers',
    'Lật thẻ 3D ánh kim nổi khối kèm tia lăng kính': 'Metallic 3D domino card flip with prism lens flare',
    'Focus Blur rạp hát kèm vệt sáng Lens Flare và nền kính nhẹ':
        'Cinematic focus blur with anamorphic lens flare and frosted glass pill',
    'Câu cũ trượt tách 4 hướng, câu mới hút từ tính khóa thẳng hàng kèm tia lăng kính':
        '4-way split exit with magnetic snap alignment and prism flare',
    'Câu cũ cuốn gió xoáy bay vút sang phải, câu mới lướt gió từ trái đáp mượt':
        'Whirlwind sweep exit to the right with smooth aerodynamic glide-in from the left',
    'Câu cũ bung tỏa như pháo hoa, câu mới nở nhảy từ tâm kèm pháo sao đa sắc':
        'Firework bloom transition from center with multicolor star confetti',
    'Câu cũ vỡ mảnh kính nghiêng rơi xuống, câu mới ghép phẳng 3D kèm tia điện từ':
        'Tilted 3D glass shard shatter with crisp electric-arc assembly',
    # SubtitleEffects dropdown items (Presets, Entrances, Colors, Trails, Kinetic, Particles)
    'Tùy chỉnh': 'Custom',
    'Không': 'None',
    'Không chuyển động': 'Static (No Entrance)',
    'Vừa': 'Balanced',
    'Rõ': 'Medium',
    'Mạnh': 'Strong',
    'Rực rỡ': 'Vivid',
    'Nhẹ · ít hạt': 'Subtle · Light',
    'Theo từ': 'By Word',
    'Theo cụm ký tự': 'By Character',
    'AMLL · Lướt chữ lụa & nâng nhịp': 'AMLL · Silk Word Sweep & Lift',
    'Mưa sao băng & tàn lửa Supernova': 'Supernova Meteors & Embers',
    'Chuỗi sét điện từ phân nhánh': 'Branching Lightning Chain',
    'Thanh sóng nhạc Equalizer Bass': 'Bass Equalizer Visualizer',
    'Tia Laser quét dọc từng dòng': 'Cyber Laser Line Scanner',
    'Tinh vân quỹ đạo Ngân Hà': 'Galactic Nebula Orbit',
    'Pháo sao 4 cánh đa sắc': '4-Point Star Confetti',
    'Tàn lửa bay ngược': 'Rising Phoenix Embers',
    'Tia lóe lăng kính': 'Anamorphic Prism Flare',
    'Mưa sao băng': 'Meteor Shower',
    'Tia chớp điện từ': 'Electric Plasma Arc',
    'Neon · Xung ánh sáng mượt': 'Neon · Smooth Light Pulse',
    'Aegisub · Vệt sáng dịu mắt': 'Aegisub · Soft Spotlight',
    'Thanh nhịp ánh sáng': 'Rhythm Light Bar',
    'Sao lấp lánh theo câu': 'Sparkling Stars',
    'Từ → phi tiêu → chữ': 'Silver Shuriken Sweep',
    'Sao băng & đuôi sáng': 'Comet & Glowing Tail',
    'Đom đóm ngọc lam': 'Mint Fireflies',
    'Tuyết pha lê': 'Crystal Snowflakes',
    'Cánh hoa bay': 'Drifting Sakura Petals',
    'Bong bóng ánh sáng': 'Luminous Bubbles',
    'Tinh thể xoay': 'Spinning Prisms',
    'Dải cực quang': 'Aurora Ribbon',
    'Màu chữ gốc': 'Original Font Color',
    'Lửa vàng rực rỡ': 'Blazing Fire Gold',
    'Anh đào Neon': 'Sakura Neon Pink',
    'Lục bảo Cyber': 'Cyber Matrix Emerald',
    'Neon Cyberpunk': 'Cyberpunk Neon',
    'Hoàng hôn rực lửa': 'Fiery Sunset',
    'Trắng ngọc điện ảnh': 'Cinema Pearl White',
    'Vàng kim sân khấu': 'Stage Royal Gold',
    'Pha lê hồng băng': 'Rose Ice Crystal',
    'Chuyển sang ngọc lam': 'Cyan Shift',
    'Gradient ngọc lam': 'Mint Gradient',
    'Gradient hoàng hôn': 'Sunset Gradient',
    'Gradient đại dương': 'Ocean Gradient',
    'Cầu vồng pastel': 'Pastel Rainbow',
    'Phi tiêu ánh bạc': 'Silver Shuriken',
    'Bầu trời sao': 'Starry Night',
    'Sao băng xanh': 'Blue Comet',
    'Vườn đom đóm': 'Firefly Garden',
    'Cánh hoa hoàng hôn': 'Sunset Petals',
    'Bong bóng mơ màng': 'Dreamy Bubbles',
    'Tinh thể tím': 'Violet Crystal',
    'Cực quang': 'Northern Aurora',
    'Mưa chữ mạnh': 'Heavy Letter Rain',
    'Domino bật nảy': 'Domino Spring',
    'Bùng nổ typography': 'Typography Burst',
    'Xoáy ngân hà': 'Galaxy Vortex',
    'Lật chữ điện ảnh': 'Cinema Flip',
    'Sóng chữ neon': 'Neon Wave',
    'Máy chữ ánh sáng': 'Light Typewriter',
    'Nhịp chữ mạnh': 'Impact Slam',
    'Mưa chữ · rơi mạnh': 'Kinetic · Letter Rain',
    'Domino · bật nảy': 'Kinetic · Domino Spring',
    'Bung chữ từ nhiều hướng': 'Kinetic · Multi-Angle Scatter',
    'Xoáy chữ vào câu': 'Kinetic · Spiral Vortex',
    'Lật chữ điện ảnh · 2D': 'Kinetic · 2D Cinema Flip',
    'Sóng chữ nối tiếp': 'Kinetic · Wave Cascade',
    'Máy chữ · hiện từng cụm': 'Kinetic · Typewriter Reveal',
    'Nhịp chữ · phóng lớn': 'Kinetic · Beat Slam',
    'Nhịp Từng Chữ · Bay theo beat': 'Beat Per Letter · Fly & Bounce',
    'Xoáy Từng Chữ · Quỹ đạo & khóa': 'Orbit Snap · Spiral & Lock',
    'Mưa Từng Chữ · Rơi nảy từng chữ': 'Letter Cascade · Elastic Drop',
    'Bung Tung Tóe · Nổ & nhảy ghép': 'Scatter Leap · Shatter & Snap',
    'Siêu Tân Tinh · Bung nổ 360°': 'Supernova · 360° Shockwave',
    'Nhất Kiếm Sét · Chém xéo ánh thép': 'Saber Slash · Diagonal Steel',
    'Đập Bass 3D · Rung chấn & sóng âm RGB': '3D Bass Drop · RGB Shockwave',
    'Cyber Glitch · Xé dải RGB & Laser': 'Cyber Glitch · RGB Split & Laser',
    'Hố Đen · Xoáy hút kỳ dị & bung quỹ đạo': 'Black Hole · Singularity Warp',
    'Từ Tính Ghép · Tách & hút khóa': 'Magnet Snap · Split & Lock',
    'Cơn Lốc Cuốn · Gió cuốn & đáp': 'Cyclone Sweep · Wind Glide',
    'Pháo Hoa Rơi · Nở bung từ tâm': 'Starburst · Center Bloom',
    'Gương Vỡ 3D · Mảnh kính phẳng': '3D Glass Shatter · Prism Shards',
    'AMLL Sing · Tan mờ quang học mượt': 'AMLL Sing · Smooth Optical Blur',
    'CapCut · Bật nảy co giãn đàn hồi': 'CapCut · Elastic Spring Bounce',
    'Hỏa Diễm · Sóng lửa bay ngược': 'Phoenix Flame · Liquid Fire',
    'Domino 3D · Lật thẻ ánh kim': '3D Domino · Metallic Card Flip',
    'Điện Ảnh · Focus Blur & Lens Flare': 'Cinema · Focus Blur & Lens Flare',
    'MV · Bung mảnh & nhảy ghép câu': 'MV · Shatter & Elastic Rebirth',
    'CapCut · Nảy lò xo đàn hồi': 'CapCut · Trampoline Bounce',
    'AE · Xoáy lốc & nam châm hút chữ': 'AE · Tornado Magnet',
    'Anime · Chém đôi tia sáng': 'Anime · Katana Flash Slice',
    '3D · Lật thẻ Domino sân khấu': '3D · Stage Domino Cascade',
    'Cyber · Giải mã Matrix': 'Cyber · Matrix Decode',
    'AMLL · Tan mờ vào nét (Focus)': 'AMLL · Optical Focus In',
    'CapCut · Bật nảy từng từ': 'CapCut · Word Pop',
    'MV · Vút ngang tốc độ (Whip)': 'MV · Speed Whip Pan',
    'MV · Sóng lượn từng từ (Wave)': 'MV · Word Wave',
    'Cyber · Nháy RGB lệch màu': 'Cyber · RGB Chromatic Glitch',
    'Bass · Đập nhịp chấn động (Slam)': 'Bass · Heavy Beat Slam',
    'Trượt êm Apple Music': 'Apple Music Silk Rise',
    'Hội tụ điện ảnh': 'Cinema Convergence',
    'Chữ rơi nhẹ': 'Gentle Drop',
    'Trượt lên': 'Smooth Rise',
    'Trượt từ trái': 'Slide from Left',
    'Trượt từ phải': 'Slide from Right',
    'Thu phóng nhẹ': 'Subtle Zoom',
    'Nảy nhẹ': 'Soft Bounce',
    'Mở từ giữa': 'Center Reveal',
    'Bừng sao khi vào câu': 'Starburst Entry',
    'Lắc nhẹ rồi ổn định': 'Gentle Swing',
    'Lượn nhẹ khi vào câu': 'Soft Flutter',
    'CapCut · Karaoke lướt sáng': 'CapCut · Glowing Karaoke Sweep',
    'AE · Mờ nét điện ảnh': 'AE · Cinema Focus Blur',
    'Cyber · Nháy RGB Glitch': 'Cyber · RGB Glitch Flash',
    'MV · Vút ngang Neon': 'MV · Neon Whip Pan',
    'MV · Bung mảnh & nhảy ghép': 'MV · Shatter & Elastic Snap',
    'AE · Xoáy lốc nam châm': 'AE · Tornado Magnet',
    'Anime · Chém đôi Katana': 'Anime · Katana Slice',
    '3D · Lật Domino sân khấu': '3D · Stage Domino Flip',
    'Siêu Tân Tinh · Bung nổ & sao băng': 'Supernova · Shatter & Meteors',
    'Nhất Kiếm Sét · Chém xéo & sét nhánh': 'Saber Slash · Blade & Lightning',
    'Đập Bass 3D · Rung chấn & sóng nhạc': '3D Bass Drop · Impact & EQ Bars',
    'Cyber Glitch · Xé RGB & Laser': 'Cyber Glitch · RGB & Laser',
    'Hố Đen · Xoáy kỳ dị & tinh vân': 'Black Hole · Singularity & Nebula',
    'AMLL Sing · Lướt lụa Apple Music': 'AMLL Sing · Apple Music Silk',
    'Nhịp Từng Chữ · Bay & nảy theo beat': 'Beat Per Letter · Fly & Bounce',
    'Xoáy Từng Chữ · Quỹ đạo & sao': 'Orbit Snap · Spiral & Stars',
    'Bung Tung Tóe · Nổ & nhảy vào vị trí': 'Scatter Leap · Burst & Snap',
    'Từ Tính Ghép · Tách 4 phía & hút khóa': 'Magnet Snap · 4-Way Lock',
    'Cơn Lốc Cuốn · Gió xoáy & đáp mượt': 'Cyclone Sweep · Smooth Glide',
    'Pháo Hoa Rơi · Nở bung & sao đa sắc': 'Starburst · Confetti Bloom',
    'Gương Vỡ 3D · Mảnh kính & tia điện': '3D Glass Shatter · Electric Shards',
    'Nảy CapCut · Bật nảy & pháo sao': 'CapCut Bounce · Spring & Stars',
    'Lật 3D · Thẻ ánh kim & lăng kính': '3D Card Flip · Metallic & Prism',
    'Hỏa Diễm · Sóng lửa & tàn lửa bay': 'Phoenix Flame · Fire & Embers',

    # --- Subtitle Editor & Video Export Dialogs ---
    'Quản Lý & Chỉnh Sửa Phụ Đề Đa Ngôn Ngữ': 'Multilingual Subtitle Editor & Sync Studio',
    'Khớp & Sửa Lời Chuẩn (Align Lyrics)': 'Align & Repair Lyrics with Reference',
    '✨ Khớp & Sửa Lời Chuẩn (Align Lyrics)': '✨ Align & Repair Lyrics',
    'Khớp & Sửa Lời Chuẩn': 'Align & Repair Lyrics',
    '✨ Khớp & Sửa Lời Chuẩn': '✨ Align & Repair Lyrics',
    'Dán Lời Bài Hát Chuẩn vào đây:': 'Paste verified reference lyrics here:',
    'Phụ Đề Gốc (Văn Bản)': 'Source Transcript (Raw Text)',
    'Bảng Phụ Đề Đa Ngôn Ngữ': 'Multilingual Cue Table',
    'Bắt đầu (s)': 'Start (s)',
    'Kết thúc (s)': 'End (s)',
    'Lời Gốc': 'Source',
    'Tiếng Anh (EN)': 'English (EN)',
    'Tiếng Việt (VI)': 'Vietnamese (VI)',
    'Thêm Dòng': 'Insert Row',
    'Xóa Dòng Đang Chọn': 'Delete Selected Row',
    'Xóa dòng đang chọn': 'Delete selected cue row',
    'Dán (Ctrl+V)': 'Paste (Ctrl+V)',
    'Dán từ Clipboard (Ctrl+V)': 'Paste from Clipboard (Ctrl+V)',
    'Import phụ đề': 'Import Subtitle',
    'Export phụ đề': 'Export Subtitle',
    '🎵 Đang đồng bộ thời gian thực': '🎵 Live playback sync active',
    'Copy tab hiện tại': 'Copy Current Tab',
    'Copy nội dung tab hiện tại': 'Copy active tab content to Clipboard',
    'Hoàn tác': 'Undo',
    'Hoàn tác thao tác (Ctrl+Z)': 'Undo (Ctrl+Z)',
    'Làm lại': 'Redo',
    'Làm lại thao tác (Ctrl+Y)': 'Redo (Ctrl+Y)',
    'Nạp lại': 'Reload',
    'Nạp lại phụ đề': 'Reload saved subtitles',
    'Dịch (AI)': 'Translate (AI)',
    'Tự động dịch (AI)': 'Auto-Translate (AI)',
    '🤖 Tự Động Dịch (AI)': '🤖 Auto-Translate (AI)',
    '⏳ Đang Dịch Thuật...': '⏳ Translating...',
    '⏳ Đang Khớp Lời...': '⏳ Aligning Lyrics...',
    'Về app': 'Back to Player',
    'Ẩn và quay lại app': 'Hide editor and return to player',
    'Ẩn cửa sổ này và quay lại ứng dụng (không lưu, không đóng)':
        'Hide this window and return to the player without closing',
    'Lưu (Ctrl+S)': 'Save (Ctrl+S)',
    'Lưu và cập nhật (Ctrl+S)': 'Save & apply changes (Ctrl+S)',
    'Ngôn ngữ gốc:': 'Source Lang:',
    # Video + Lyric Export Dialog
    'Xuất video + lyric': 'Export Video + Lyrics',
    'Xuất video kèm phụ đề / lyric': 'Export Video + Lyrics',
    'Xuất video kèm phụ đề / lyric đang hiển thị': 'Export video with burned-in lyrics & visual effects',
    'Xem trước bố cục đầu ra và tinh chỉnh trước khi render.': 'Preview canvas framing and fine-tune encoder settings before rendering.',
    'Khôi phục đề xuất': 'Restore Recommended',
    'Bản xem trước': 'Canvas Preview',
    'PREVIEW KHUNG XUẤT': 'EXPORT CANVAS PREVIEW',
    'Khung xem trước video\n(thumbnail chưa sẵn sàng)': 'Video canvas preview\n(thumbnail loading)',
    'Thumbnail chỉ dùng để kiểm tra bố cục; video xuất vẫn lấy hình từ file gốc.':
        'Thumbnail is for layout framing only; exported video renders from the original source file.',
    'Chỉ đổi câu dùng để xem trước, không thay đổi lyric xuất.':
        'Changes preview sample cue only; all cues are rendered in the exported video.',
    'Theo video nguồn • Vừa khung • Chất lượng cao': 'Source aspect • Fit • High quality',
    'Thiết lập đầu ra': 'Output Configuration',
    'Nguồn': 'Source',
    'Vuông': 'Square',
    'MP4 — tương thích rộng': 'MP4 — Universal compatibility',
    'MKV — giữ audio linh hoạt': 'MKV — Lossless audio stream-copy',
    'Theo video gốc': 'Match source video',
    '16:9 — YouTube / màn hình': '16:9 — YouTube / Widescreen',
    '9:16 — Shorts / Reels / TikTok': '9:16 — Shorts / Reels / TikTok',
    '1:1 — Vuông': '1:1 — Square',
    '4:5 — Social portrait': '4:5 — Social Portrait',
    '4:3 — Cổ điển': '4:3 — Classic',
    '3:2 — Cinematic': '3:2 — Photography',
    '21:9 — Ultrawide': '21:9 — Ultrawide Cinema',
    'Theo độ phân giải nguồn': 'Match source resolution',
    'Tùy chỉnh…': 'Custom…',
    'Đổi chiều rộng và chiều cao': 'Swap custom width and height',
    'Vừa khung — giữ trọn hình': 'Fit (Contain) — Preserve full frame',
    'Lấp đầy — crop phần dư': 'Fill (Cover) — Crop edges',
    'Kéo giãn — không crop': 'Stretch — Fill without cropping',
    'Vừa khung': 'Fit',
    'Lấp đầy': 'Cover',
    'Kéo giãn': 'Stretch',
    'Đen': 'Pure Black',
    'Xám đậm': 'Studio Dark Gray',
    'Trắng': 'Pure White',
    'Theo video nguồn': 'Match source FPS',
    'Rất cao — CRF 16 / CQ 19': 'Ultra — CRF 16 / CQ 19',
    'Cao — CRF 18 / CQ 21': 'High — CRF 18 / CQ 21',
    'Cân bằng — CRF 20 / CQ 23': 'Balanced — CRF 20 / CQ 23',
    'Nhẹ — CRF 23 / CQ 26': 'Compact — CRF 23 / CQ 26',
    'Tự động — Ưu tiên GPU NVIDIA (NVENC ⚡)': 'Auto — Prefer NVIDIA GPU (NVENC ⚡)',
    'GPU NVIDIA — h264_nvenc (Siêu tốc ⚡)': 'NVIDIA GPU — h264_nvenc (Ultra-fast ⚡)',
    'Tự động — CPU libx264 (Chưa có NVENC)': 'Auto — CPU libx264 (NVENC unavailable)',
    'GPU NVIDIA — h264_nvenc (Tự chuyển CPU nếu thiếu)': 'NVIDIA GPU — h264_nvenc (Auto CPU fallback)',
    'CPU — libx264 (Chuẩn phần mềm)': 'CPU — libx264 (Software standard)',
    'Lyric / subtitle': 'Lyrics & Safe Area',
    'Định dạng': 'Container',
    'Tỉ lệ': 'Aspect Ratio',
    'Độ phân giải': 'Resolution',
    'Kích thước': 'Dimensions',
    'Bố cục video': 'Video Framing',
    'Nền phần trống': 'Pad Background',
    'Chất lượng': 'Quality',
    'Bộ mã hóa': 'Video Encoder',
    'Chống cắt chữ/effect ở mép khung': 'Prevent lyric/effect edge clipping (Safe Area)',
    '0% giữ vị trí như trong app; tăng lề nếu muốn title-safe area kiểu editor.':
        '0% preserves exact in-app placement; increase margins for broadcast title-safe padding.',
    'Ghi đè riêng khi xuất': 'Export-Only Overrides',
    'Ghi đè cỡ chữ khi xuất': 'Override font size for export',
    'Đưa vị trí sub về như trong app': 'Reset subtitle position to live view',
    'Ghi đè độ trong nền subtitle': 'Override background pill opacity',
    'Tự động tăng tốc bằng GPU NVIDIA (NVENC ⚡) khi khả dụng, tự chuyển sang CPU nếu cần; audio sẽ copy khi container hỗ trợ.':
        'Automatically accelerates via NVIDIA GPU (NVENC ⚡) when available with seamless CPU fallback; lossless audio stream-copy when supported.',
    'Tiếp tục xuất': 'Export Video',
    'Đang chuẩn bị bản xuất…': 'Preparing video export…',
    'Lề ngang': 'Horizontal Margin',
    'Lề dọc': 'Vertical Margin',
    'Dịch ngang': 'Horizontal Offset',
    'Dịch dọc (+ lên)': 'Vertical Offset (+ Up)',

    # --- Media Info Popup ---
    'Thông Tin Tệp Tin Chi Tiết (Media Info)': 'Detailed Media & Stream Information',
    '🎵 Tên bài hát đang phát': '🎵 Active Track',
    'Tổng Quan': 'Overview',
    'Kỹ Thuật (Codec)': 'Stream Codecs',
    'Description (Meta)': 'Metadata / Description',
    'Đóng Tâm Bảo': 'Close',
    'Tên tệp tin:': 'File Name:',
    'Đường dẫn gốc:': 'Source Path:',
    'Định dạng đuôi:': 'Container Extension:',
    'Kích thước tệp:': 'File Size:',
    'Thời lượng bài:': 'Duration:',
    'Nghệ sĩ phát:': 'Artist / Channel:',
    'ID nhận diện MD5:': 'Media ID (MD5):',
    'Ngày sửa đổi cuối:': 'Last Modified:',
    'Mã hóa Video (Codec):': 'Video Codec:',
    'Độ phân giải thực:': 'Video Resolution:',
    'Tốc độ khung hình (FPS):': 'Frame Rate (FPS):',
    'Tỷ lệ khung hình (Aspect):': 'Aspect Ratio:',
    'Mã hóa Âm thanh (Audio):': 'Audio Codec:',
    'Tần số lấy mẫu (Sample):': 'Sample Rate:',
    'Kênh âm thanh (Channels):': 'Audio Channels:',
    'Chất lượng luồng (Bitrate):': 'Stream Bitrate:',
    'Đang quét... (Auto)': 'Probing…',
    'Không có mô tả': 'No embedded description',
    'Đang đọc mô tả…': 'Reading metadata…',
    'Không có tiêu đề': 'Untitled',
    'Chưa rõ': 'Unknown',
    'Không có': 'None',
    'Không có bài hát': 'No track loaded',
    'Đang đọc…': 'Probing stream…',
}

_DAY_VI_TO_EN = {
    'THỨ HAI': 'MONDAY',
    'THỨ BA': 'TUESDAY',
    'THỨ TƯ': 'WEDNESDAY',
    'THỨ NĂM': 'THURSDAY',
    'THỨ SÁU': 'FRIDAY',
    'THỨ BẢY': 'SATURDAY',
    'CHỦ NHẬT': 'SUNDAY',
    'Thứ Hai': 'Monday',
    'Thứ Ba': 'Tuesday',
    'Thứ Tư': 'Wednesday',
    'Thứ Năm': 'Thursday',
    'Thứ Sáu': 'Friday',
    'Thứ Bảy': 'Saturday',
    'Chủ Nhật': 'Sunday',
}

_RE_COUNT_VIDEOS = re.compile(r'^(\d+)\s+video$', re.IGNORECASE)
_RE_COUNT_SONGS = re.compile(r'^(\d+)\s+bài(?:\s+hát)?$')
_RE_COUNT_PLAYS = re.compile(r'^(\d+)\s+lượt(?:\s+nghe)?$')
_RE_SELECTED_SONGS = re.compile(r'^Đã chọn:\s*(\d+)\s+bài$')
_RE_WATCH_COUNT = re.compile(r'^Xem\s+(\d+)\s+lần$')
_RE_PAUSED_AT = re.compile(r'^Dừng tại\s+(.+)$')
_RE_FORYOU_STATUS = re.compile(r'^Bài hát\s*-\s*(.+)$')
_RE_TOTAL_DURATION = re.compile(r'^Tổng thời lượng\s+(.+)$')
_RE_LISTENED_DUR = re.compile(r'^Đã nghe\s+(.+)$')
_RE_TODAY_TIME = re.compile(r'^Hôm nay\s+(\d{1,2}:\d{2})$')
_RE_HIST_TODAY = re.compile(r'^(HÔM NAY|Hôm nay)\s*—\s*(.+)$')
_RE_HIST_YESTERDAY = re.compile(r'^(HÔM QUA|Hôm qua)\s*—\s*(.+)$')
_RE_HIST_WEEKDAY = re.compile(
    r'^(THỨ HAI|THỨ BA|THỨ TƯ|THỨ NĂM|THỨ SÁU|THỨ BẢY|CHỦ NHẬT|'
    r'Thứ Hai|Thứ Ba|Thứ Tư|Thứ Năm|Thứ Sáu|Thứ Bảy|Chủ Nhật),\s*(.+)$'
)
_RE_EXPORT_CUE = re.compile(r'^Câu\s+(\d+):\s*(.+)$')
_RE_EXPORT_FONT_NOTE = re.compile(r'^Tắt = dùng cỡ chữ đang hiển thị trong app \((\d+)px\)\.$')
_RE_ACTIVE_PROFILE = re.compile(r'^Đang chọn:\s*(.+)$')
_RE_KARAOKE_PROFILE = re.compile(r'^🎤 Karaoke ·\s*(.+)$')
_RE_CUSTOM_PROFILE = re.compile(r'^Tùy chỉnh ·\s*(.+)$')
_RE_PEQ_COUNT = re.compile(r'^(\d+)/16\s+dải PEQ$')
_RE_EQ_BTN_PEQ = re.compile(r'^Equalizer\s*·\s*PEQ\s*(\d+)\s*dải$')
_RE_DISCONNECTED_DEV = re.compile(r'^(.+)\s+\(Chưa cắm\)$')
_RE_REMOVE_FOLDER_TIP = re.compile(r'^Gỡ thư mục\s+(.+)$')
_RE_SAMPLES_COUNT = re.compile(r'^([\d,]+)\s+mẫu$')
_RE_REMAINING_CLIPS = re.compile(r'^Còn\s+([\d,]+)\s+mẫu$')
_RE_PRESERVED_DR = re.compile(r'^Giữ nguyên\s+\(([^)]+)\)$')
_RE_CROSSFEED_DB = re.compile(r'^Hòa kênh\s+(.+)$')


def _translate_vi_duration(dur_text: str) -> str:
    s = dur_text.strip()
    s = re.sub(r'(\d+)\s*giờ', r'\1h', s)
    s = re.sub(r'(\d+)\s*phút', r'\1m', s)
    s = re.sub(r'(\d+)\s*giây', r'\1s', s)
    return s


def _translate_benchmark_dynamic(s: str) -> str | None:
    """Translate parameterized acoustic benchmark conclusions, findings, and table values."""
    m = _RE_SAMPLES_COUNT.match(s)
    if m:
        return f'{m.group(1)} samples'
    m = _RE_REMAINING_CLIPS.match(s)
    if m:
        return f'{m.group(1)} clips left'
    m = _RE_PRESERVED_DR.match(s)
    if m:
        return f'Preserved ({m.group(1)})'
    m = _RE_CROSSFEED_DB.match(s)
    if m:
        return f'Crossfeed {m.group(1)}'

    if s.startswith('Tốt hơn bản gốc về độ trong trẻo: Đã khử sạch '):
        m = re.search(r'Đã khử sạch ([\d,]+) điểm vượt trần', s)
        n = m.group(1) if m else 'all'
        return (
            f'Cleaner than raw source: eliminated {n} inter-sample clipping peaks during loud passages '
            'while preserving 100% original vocal & instrument detail.'
        )
    if s.startswith('Tốt hơn bản gốc về độ trong trẻo: Đã hạ đỉnh cao trào toàn bài ('):
        m = re.search(r'\(([^)]+)\)', s)
        pk = m.group(1) if m else ''
        return (
            f'Cleaner than raw source: tamed full-track climax peaks ({pk}) into safe headroom '
            'while preserving 100% original vocal & instrument detail.'
        )
    if s.startswith('Đã khử sạch ') and 'điểm vượt trần về 0 clip' in s:
        m = re.search(r'Đã khử sạch ([\d,]+)', s)
        return f'Eliminated {m.group(1) if m else "all"} inter-sample peaks down to 0 clips.'
    if s.startswith('Đã hạ đỉnh cao trào toàn bài ('):
        m = re.search(r'\(([^)]+)\)', s)
        return f'Lowered full-track climax peak ({m.group(1) if m else ""}) into clean headroom.'
    if s.startswith('File gốc có ') and 'điểm vượt ngưỡng khi mở to' in s:
        m = re.search(r'File gốc có ([\d,]+)', s)
        return f'Raw file has {m.group(1) if m else ""} peaks exceeding 0 dBTP at high volume.'
    if s.startswith('Đoạn cao trào toàn bài vượt trần ('):
        m = re.search(r'\(([^)]+)\)', s)
        return f'Full-track climax exceeds digital ceiling ({m.group(1) if m else ""}).'
    if s.startswith('Xuất hiện ') and 'điểm vỡ đỉnh; nên bật Tự giảm Preamp' in s:
        m = re.search(r'Xuất hiện ([\d,]+)', s)
        return f'{m.group(1) if m else ""} clipped samples detected; enable Auto Preamp Guard.'
    if s.startswith('Biến thiên nhẹ ') and 'theo đáp tuyến EQ' in s:
        m = re.search(r'Biến thiên nhẹ ([^\s]+ dB)', s)
        return f'Gentle {m.group(1) if m else ""} crest shift from tonal EQ curve.'
    if s.startswith('Giảm ') and 'độ động so với bản gốc' in s:
        m = re.search(r'Giảm ([^\s]+ dB)', s)
        return f'Dynamic range reduced by {m.group(1) if m else ""} vs raw source.'
    if s.startswith('Lệch ±') and 'dễ làm biến dạng giọng hát' in s:
        m = re.search(r'±([\d.]+ dB)', s)
        return f'±{m.group(1) if m else ""} deviation may color vocal timbre.'
    if s.startswith('Đang phát nguyên gốc chưa xử lý. File gốc có '):
        m = re.search(r'File gốc có ([\d,]+)', s)
        return (
            f'Playing unprocessed raw stream. Source has {m.group(1) if m else ""} inter-sample peaks — '
            'enable Bit-Pure Original or Hi-Fi Master for clean headroom.'
        )
    if s.startswith('Đoạn trích hiện tại êm nhưng cao trào toàn bài vượt ngưỡng ('):
        m = re.search(r'\(([^)]+)\)', s)
        return (
            f'Current excerpt is calm, but full-track climax exceeds 0 dBTP ({m.group(1) if m else ""}) — '
            'enable Bit-Pure Original or Hi-Fi Master for clean headroom.'
        )
    if s.startswith('Đang kém hơn bản gốc: Xuất hiện '):
        m = re.search(r'Xuất hiện ([\d,]+)', s)
        return (
            f'Post-DSP clipping detected ({m.group(1) if m else ""} clipped samples). '
            'Enable Auto Preamp Guard or Loudness Normalization.'
        )
    if s.startswith('Đang kéo EQ quá mạnh (±'):
        m = re.search(r'±([\d.]+ dB)', s)
        return f'Heavy EQ boost (±{m.group(1) if m else ""}) may cause muddiness or glare; reduce EQ sliders closer to 0 dB.'
    if s.startswith('Sạch hơn gốc (') or s.startswith('Độ sạch ngang bản gốc ('):
        out = s
        out = out.replace('Sạch hơn gốc (', 'Cleaner peaks (')
        out = out.replace('Độ sạch ngang bản gốc (0 vỡ tiếng, giữ nguyên độ nảy), màu âm được chỉnh ', 'Clean as source (0 clips, full dynamics) with ')
        out = re.sub(r'khử ([\d,]+) điểm vượt trần về 0', r'eliminated \1 clips', out)
        out = re.sub(r'hạ đỉnh cao trào ([^\s]+ dBTP) về vùng sạch', r'tamed \1 climax peak', out)
        out = out.replace('hạ đỉnh về ngưỡng sạch', 'safe DAC headroom')
        out = out.replace(') kèm tinh chỉnh ', ') + ')
        out = out.replace('âm trầm ấm và sâu hơn', 'warmer deeper bass')
        out = out.replace('gọn bớt âm trầm', 'tighter low-end')
        out = out.replace('giọng hát nổi rõ hơn', 'clearer vocal presence')
        out = out.replace('dịu bớt dải trung gắt', 'smoother upper-mids')
        out = out.replace('dải cao thoáng sáng hơn', 'airier treble')
        out = out.replace('mượt bớt âm sibilance/chói', 'tamed sibilance')
        out = out.replace('mở không gian như loa ngoài', '30° speaker soundstage')
        out = out.replace('cân chỉnh nhẹ nhàng', 'subtle tonal shaping')
        out = out.replace(' và ', ' and ')
        out = out.replace('Bấm "Nghe thử A/B" bên dưới để tự kiểm chứng bằng tai.', 'Click "A/B Audition" below to compare by ear.')
        out = out.replace('Hãy bấm "Nghe thử A/B" để xem hợp tai bạn hơn không.', 'Click "A/B Audition" to compare by ear.')
        return out
    if s.startswith('Nghe ') or s.startswith('Chỉnh đậm ('):
        out = s
        if out.startswith('Nghe '):
            out = 'Voicing: ' + out[5:]
        out = out.replace('Chỉnh đậm (', 'Bold voicing (')
        out = out.replace('); hãy nghe thử A/B.', '); audition A/B to verify.')
        out = out.replace('âm trầm ấm và sâu hơn', 'warmer deeper bass')
        out = out.replace('gọn bớt âm trầm', 'tighter low-end')
        out = out.replace('giọng hát nổi rõ hơn', 'clearer vocal presence')
        out = out.replace('dịu bớt dải trung gắt', 'smoother upper-mids')
        out = out.replace('dải cao thoáng sáng hơn', 'airier treble')
        out = out.replace('mượt bớt âm sibilance/chói', 'tamed sibilance')
        out = out.replace('mở không gian như loa ngoài', '30° speaker soundstage')
        out = out.replace('cân chỉnh nhẹ nhàng', 'subtle tonal shaping')
        out = out.replace(' và ', ' & ')
        return out

    # Clinical headline & footer & findings
    if any(
        k in s
        for k in (
            'Nền nhiễu ',
            'Đáp tuyến ',
            'Đầu ra DAC ',
            'Khớp chuẩn phát YouTube',
            'Đạt trần phát sạch EBU R128',
            'Đỉnh gốc ',
            'mẫu clip',
            'Băng thông file ',
            'Băng thông thực:',
            'Đang đo kiểm…',
            'Đã chép báo cáo đo kiểm',
            'Đang phát A ·',
            'Đang phát B ·',
        )
    ):
        out = s
        out = out.replace('Đang đo kiểm…', 'Analyzing…')
        out = out.replace('Đã chép báo cáo đo kiểm', 'Copied benchmark report')
        out = out.replace('Đáp tuyến phẳng 0.00 dB', 'Flat 0.00 dB response')
        out = out.replace('Đáp tuyến 0.00 dB', '0.00 dB response')
        out = out.replace('Đầu ra DAC ', 'DAC Output ')
        out = out.replace('Khớp chuẩn phát YouTube', 'YouTube −14 LUFS target')
        out = out.replace('Đạt trần phát sạch EBU R128', 'Clean EBU R128 headroom')
        out = out.replace('Nền nhiễu số:', 'Noise Floor:')
        out = out.replace('Nền nhiễu ', 'Noise floor ')
        out = out.replace('Đỉnh thực ', 'True peak ')
        out = out.replace('đỉnh thực ', 'true peak ')
        out = out.replace('Đỉnh gốc ', 'Raw peak ')
        out = out.replace('Đỉnh ', 'Peak ')
        out = out.replace('mẫu vượt 0 dBTP', 'samples > 0 dBTP')
        out = out.replace('nên bật Nguyên bản để giảm về ≤ -1.0 dBTP.', 'enable Bit-Pure Original to cap at ≤ -1.0 dBTP.')
        out = out.replace('nằm dưới trần 0 dBTP (0 mẫu clip).', 'safely below 0 dBTP ceiling (0 clipped samples).')
        out = out.replace('Tín hiệu giữ nguyên bản 100%, không can thiệp EQ.', '100% uncolored signal, zero EQ applied.')
        out = out.replace('Băng thông đo thực ', 'Measured bandwidth ')
        out = out.replace('Băng thông thực:', 'Bandwidth:')
        out = out.replace('Băng thông file ', 'Source bandwidth ')
        out = out.replace('Định dạng:', 'Format:')
        out = out.replace('Đầu ra:', 'Output:')
        out = out.replace('0 mẫu clip', '0 clips')
        out = out.replace('mẫu clip', 'clips')
        out = out.replace('đạt trần ≤ -1.0 dBTP', '≤ -1.0 dBTP ceiling')
        out = out.replace('không nén động', 'zero dynamic compression')
        out = out.replace('DSP giữ nguyên độ động', 'DSP preserves full dynamics')
        out = out.replace('Lưu ý: bản thu gốc nén sẵn khá chặt', 'Note: original master is heavily compressed')
        out = out.replace('cân nhắc giảm bớt EQ.', 'consider reducing EQ gain.')
        out = out.replace('Bật Tự giảm Preamp hoặc Cân bằng âm lượng.', 'Enable Auto Preamp Guard or Loudness Normalization.')
        out = out.replace('Đang phát A · Bản gốc', 'Playing A · Raw Source')
        out = out.replace('Đang phát B · Sau xử lý', 'Playing B · Processed')
        out = out.replace('Đang cân bằng ', 'Matched at ')
        out = out.replace('chênh gốc ', 'offset ')
        out = out.replace('(chế độ âm lượng gốc, không bù dB)', '(unmatched raw level)')
        return out
    return None


def translate_text(text: str, lang: str | None = None) -> str:
    """Translate a known Vietnamese UI string to English when `lang == 'en'`."""
    if not text:
        return text
    target_lang = get_language() if lang is None else normalize_language(lang)
    if target_lang != 'en':
        return text

    stripped = text.strip()
    if not stripped:
        return text

    # 1. Exact phrasebook lookup (preserving leading/trailing whitespace)
    direct = VI_TO_EN.get(stripped)
    if direct is not None:
        if text == stripped:
            return direct
        lead = text[: len(text) - len(text.lstrip())]
        tail = text[len(text.rstrip()) :]
        return f'{lead}{direct}{tail}'

    # 2. Karaoke ★ recommended prefix (e.g. '★ AMLL Sing', '★ AMLL · Lướt chữ lụa & nâng nhịp')
    if stripped.startswith('★ '):
        inner = stripped[2:].strip()
        if inner.startswith('Đề xuất chuẩn cho Karaoke từng chữ · '):
            rest = inner[len('Đề xuất chuẩn cho Karaoke từng chữ · ') :].strip()
            return f'★ Recommended for Word Karaoke · {translate_text(rest, "en")}'
        tr_inner = translate_text(inner, 'en')
        return f'★ {tr_inner}'

    # 3. Qt mnemonic '&&' escape (e.g. QGroupBox title 'Hiệu ứng phụ đề && Xem thử')
    if '&&' in stripped:
        unescaped = stripped.replace('&&', '&')
        tr_unesc = VI_TO_EN.get(unescaped)
        if tr_unesc is not None:
            return tr_unesc.replace('&', '&&')

    # 4. PlaybackBar rich-text placeholders & Smart Resume HTML / tooltip
    if 'Chưa có tiêu đề' in text and 'Chọn video để phát' in text:
        return (
            text.replace('Chưa có tiêu đề', 'No track playing')
            .replace('Chọn video để phát', 'Select a video or song to play')
        )
    if '▶ Bấm Phát để tiếp tục tại ' in text:
        return text.replace('▶ Bấm Phát để tiếp tục tại ', '▶ Press Play to resume at ')
    if text.startswith('Phiên nghe gần nhất: '):
        return (
            text.replace('Phiên nghe gần nhất: ', 'Last session: ')
            .replace('\nNghệ sĩ: ', '\nArtist: ')
            .replace('\nDừng tại: ', '\nPaused at: ')
        )

    # 5. Structured dynamic patterns (counts, dates, badges, export summary)
    m = _RE_COUNT_VIDEOS.match(stripped)
    if m:
        n = int(m.group(1))
        return f'{n} video' if n == 1 else f'{n} videos'

    m = _RE_COUNT_SONGS.match(stripped)
    if m:
        n = int(m.group(1))
        return f'{n} track' if n == 1 else f'{n} tracks'

    m = _RE_COUNT_PLAYS.match(stripped)
    if m:
        n = int(m.group(1))
        return f'{n} play' if n == 1 else f'{n} plays'

    m = _RE_SELECTED_SONGS.match(stripped)
    if m:
        n = int(m.group(1))
        return f'Selected: {n} track' if n == 1 else f'Selected: {n} tracks'

    m = _RE_WATCH_COUNT.match(stripped)
    if m:
        n = int(m.group(1))
        return f'Viewed {n} time' if n == 1 else f'Viewed {n} times'

    m = _RE_PAUSED_AT.match(stripped)
    if m:
        return f'Paused at {m.group(1)}'

    m = _RE_FORYOU_STATUS.match(stripped)
    if m:
        return f'Track - {m.group(1)}'

    m = _RE_TOTAL_DURATION.match(stripped)
    if m:
        return f'Total {m.group(1)}'

    m = _RE_LISTENED_DUR.match(stripped)
    if m:
        return f'Listened {_translate_vi_duration(m.group(1))}'

    if any(u in stripped for u in (' giờ', ' phút', ' giây')) and re.match(r'^\d+\s*(giờ|phút|giây)', stripped):
        return _translate_vi_duration(stripped)

    m = _RE_TODAY_TIME.match(stripped)
    if m:
        return f'Today {m.group(1)}'

    m = _RE_HIST_TODAY.match(stripped)
    if m:
        tag = 'TODAY' if m.group(1).isupper() else 'Today'
        return f'{tag} — {m.group(2)}'

    m = _RE_HIST_YESTERDAY.match(stripped)
    if m:
        tag = 'YESTERDAY' if m.group(1).isupper() else 'Yesterday'
        return f'{tag} — {m.group(2)}'

    m = _RE_HIST_WEEKDAY.match(stripped)
    if m:
        return f'{_DAY_VI_TO_EN.get(m.group(1), m.group(1))}, {m.group(2)}'

    m = _RE_EXPORT_CUE.match(stripped)
    if m:
        return f'Cue {m.group(1)}: {m.group(2)}'

    m = _RE_EXPORT_FONT_NOTE.match(stripped)
    if m:
        return f'Off = keep live in-app font size ({m.group(1)}px).'

    if stripped.startswith('Đầu ra: '):
        rest = (
            stripped[len('Đầu ra: ') :]
            .replace('độ phân giải nguồn', 'source resolution')
            .replace('FPS nguồn', 'source FPS')
            .replace('• chữ ', '• font ')
        )
        return f'Output: {rest}'

    m = _RE_ACTIVE_PROFILE.match(stripped)
    if m:
        return f'Active: {translate_text(m.group(1), "en")}'

    m = _RE_KARAOKE_PROFILE.match(stripped)
    if m:
        return f'🎤 Karaoke · {translate_text(m.group(1), "en")}'

    m = _RE_CUSTOM_PROFILE.match(stripped)
    if m:
        return f'Custom · {translate_text(m.group(1), "en")}'

    m = _RE_PEQ_COUNT.match(stripped)
    if m:
        return f'{m.group(1)}/16 PEQ bands'

    m = _RE_EQ_BTN_PEQ.match(stripped)
    if m:
        return f'Equalizer  ·  PEQ ({m.group(1)} bands)'

    m = _RE_DISCONNECTED_DEV.match(stripped)
    if m:
        return f'{m.group(1)} (Disconnected)'

    m = _RE_REMOVE_FOLDER_TIP.match(stripped)
    if m:
        return f'Remove folder {m.group(1)}'

    if stripped.startswith('<b>📂 Bài hiện tại:</b>'):
        return text.replace('<b>📂 Bài hiện tại:</b>', '<b>📂 Active Track:</b>').replace('Đang nạp...', 'Loading...')
    if stripped.startswith('<b>📂 File phụ đề:</b>'):
        return text.replace('<b>📂 File phụ đề:</b>', '<b>📂 Subtitle File:</b>')

    if '⬇ Chưa cài' in stripped or '✔ Đã cài' in stripped:
        return text.replace('⬇ Chưa cài', '⬇ Not installed').replace('✔ Đã cài', '✔ Installed')

    if stripped.startswith('Chuyển mã MP3 ') and 'kbps để tương thích' in stripped:
        m_mp3 = re.search(r'(\d+)\s*kbps', stripped)
        br = m_mp3.group(1) if m_mp3 else '320'
        return f'Transcodes to MP3 {br} kbps for legacy compatibility (does not restore lost lossy detail).'

    if stripped.startswith('Nguồn: ') and '\nXử lý: ' in stripped:
        return (
            stripped.replace('Nguồn: ', 'Source: ')
            .replace('\nXử lý: ', '\nDSP: ')
            .replace('\nĐầu ra: ', '\nOutput: ')
            .replace('Chưa phát', 'Idle')
            .replace('Nguyên gốc', 'Bit-Exact Raw')
        )

    bench_tr = _translate_benchmark_dynamic(stripped)
    if bench_tr is not None:
        return bench_tr

    # 6. Multi-segment compound metadata (e.g. '03:08  ·  Xem 21 lần', 'Chưa phát  ›  64-bit ...')
    for sep in ('  ·  ', ' • ', '  ›  '):
        if sep in stripped:
            parts = stripped.split(sep)
            tr_parts = [translate_text(p, 'en') for p in parts]
            if tr_parts != parts:
                return sep.join(tr_parts)

    return text


def _translate_single_property(
    obj: QObject,
    prop_key: str,
    getter: Callable[[], str],
    setter: Callable[[str], None],
    lang: str,
) -> None:
    cur = getter() or ''
    saved_vi = obj.property(prop_key)
    if lang == 'en':
        if saved_vi is None or (cur != translate_text(str(saved_vi), 'en') and cur != str(saved_vi)):
            if translate_text(cur, 'en') != cur:
                obj.setProperty(prop_key, cur)
                saved_vi = cur
        if saved_vi is not None:
            new_en = translate_text(str(saved_vi), 'en')
            if new_en != cur:
                setter(new_en)
    else:
        if saved_vi is not None:
            expected_en = translate_text(str(saved_vi), 'en')
            if cur == expected_en and cur != str(saved_vi):
                setter(str(saved_vi))


def translate_widget_tree(root: QWidget | None, lang: str | None = None) -> None:
    """Safely translate static labels/buttons/placeholders/tabs/titles & itemData combos under `root`."""
    if root is None:
        return
    target = get_language() if lang is None else normalize_language(lang)

    widgets: list[QWidget] = [root]
    widgets.extend(root.findChildren(QWidget))

    for w in widgets:
        # Never touch live lyric rendering surfaces or hidden legacy SettingsPage owner bin
        if type(w).__name__ in ('SubtitleLayer', '_ExportLabel', 'DraggableSubtitle'):
            continue
        p = w
        in_legacy = False
        while p is not None:
            if p.objectName() == 'legacySettingsOwnerBin':
                in_legacy = True
                break
            p = p.parentWidget()
        if in_legacy:
            continue

        if w.isWindow():
            _translate_single_property(w, '_i18n_vi_wtitle', w.windowTitle, w.setWindowTitle, target)

        if w.toolTip():
            _translate_single_property(w, '_i18n_vi_tip', w.toolTip, w.setToolTip, target)

        if isinstance(w, QGroupBox):
            _translate_single_property(w, '_i18n_vi_title', w.title, w.setTitle, target)
        elif isinstance(w, (QLabel, QAbstractButton)):
            _translate_single_property(w, '_i18n_vi_text', w.text, w.setText, target)
        elif isinstance(w, QLineEdit):
            _translate_single_property(
                w, '_i18n_vi_ph', w.placeholderText, w.setPlaceholderText, target
            )
        elif isinstance(w, (QTextEdit, QPlainTextEdit)):
            _translate_single_property(
                w, '_i18n_vi_ph', w.placeholderText, w.setPlaceholderText, target
            )
        elif isinstance(w, QTabWidget):
            for idx in range(w.count()):
                key = f'_i18n_vi_tab_{idx}'
                _translate_single_property(
                    w,
                    key,
                    lambda i=idx, tw=w: tw.tabText(i),
                    lambda val, i=idx, tw=w: tw.setTabText(i, val),
                    target,
                )
        elif isinstance(w, QComboBox) and not bool(w.property('_i18n_skip_combo')):
            # Safe rule: translate any combo that stores canonical `itemData` (UserRole)
            # or explicitly opts in via `_i18n_safe_combo`. Legacy `.currentText()`-persisted
            # combos have all `itemData(i) is None` and remain 100% untouched.
            has_canonical_data = bool(w.property('_i18n_safe_combo')) or (
                w.count() > 0 and any(w.itemData(i) is not None for i in range(w.count()))
            )
            if has_canonical_data:
                blocker = QSignalBlocker(w)
                for idx in range(w.count()):
                    key = f'_i18n_vi_item_{idx}'
                    _translate_single_property(
                        w,
                        key,
                        lambda i=idx, cb=w: cb.itemText(i),
                        lambda val, i=idx, cb=w: cb.setItemText(i, val),
                        target,
                    )
                del blocker
        elif isinstance(w, QTableView) and w.model() is not None:
            model = w.model()
            if hasattr(model, 'retranslate_headers'):
                model.retranslate_headers(target)

    for action in root.findChildren(QAction):
        if action.text():
            _translate_single_property(action, '_i18n_vi_act', action.text, action.setText, target)
        if action.toolTip():
            _translate_single_property(action, '_i18n_vi_act_tip', action.toolTip, action.setToolTip, target)


class AppLanguageManager(QObject):
    """Application-scoped live translator attached to MainWindow."""

    language_changed = Signal(str)

    def __init__(self, window: QWidget, settings: QSettings | None = None):
        super().__init__(window)
        self.window = window
        self._settings = settings
        self._callback = self._on_global_language_changed
        register_language_listener(self._callback)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self.destroyed.connect(self._cleanup_on_destroy)

        if settings is not None:
            lang = normalize_language(settings.value(_SETTINGS_KEY, 'vi'))
            set_language(lang, persist=False)
        else:
            lang = reload_language_from_settings()
        if lang == 'en':
            QTimer.singleShot(0, lambda: self.apply_language('en'))

    def _cleanup_on_destroy(self, *_args) -> None:
        unregister_language_listener(self._callback)
        app = QApplication.instance()
        if app is not None:
            try:
                app.removeEventFilter(self)
            except RuntimeError:
                pass

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if _CURRENT_LANG == 'en' and event.type() == QEvent.Type.Show:
            if isinstance(watched, (QDialog, QMenu)) or (
                isinstance(watched, QWidget) and watched.isWindow() and watched is not self.window
            ):
                QTimer.singleShot(0, lambda w=watched: self._translate_popup_safe(w))
        return False

    @staticmethod
    def _translate_popup_safe(widget: QWidget) -> None:
        try:
            if widget is not None and get_language() == 'en':
                if hasattr(widget, 'retranslate_ui'):
                    widget.retranslate_ui('en')
                else:
                    translate_widget_tree(widget, 'en')
        except RuntimeError:
            pass

    def _on_global_language_changed(self, lang: str) -> None:
        self.apply_language(lang)
        self.language_changed.emit(lang)

    def apply_language(self, lang: str) -> None:
        target = normalize_language(lang)
        win = self.window
        if win is None:
            return

        # 1. Sidebar dedicated retranslation (preserves UserRole + 1 / + 2 / + 4 contracts)
        sidebar = getattr(win, 'sidebar', None)
        if sidebar is not None and hasattr(sidebar, 'retranslate'):
            sidebar.retranslate(target)

        # 2. Dedicated Studio views, Audio Popup & Audio Signal Lab
        fx = getattr(win, 'audio_effects', None)
        if fx is not None:
            studio = getattr(fx, 'settings_studio', None)
            if studio is not None and hasattr(studio, 'retranslate_ui'):
                studio.retranslate_ui(target)
            dl_studio = getattr(fx, 'download_studio', None)
            if dl_studio is not None and hasattr(dl_studio, 'retranslate_ui'):
                dl_studio.retranslate_ui(target)
            panel = getattr(fx, 'panel', None)
            if panel is not None:
                if hasattr(panel, 'retranslate_ui'):
                    panel.retranslate_ui(target)
                else:
                    translate_widget_tree(panel, target)
            bench = getattr(fx, '_benchmark_page', None) or getattr(fx, 'benchmark_page', None)
            if bench is not None and hasattr(bench, 'retranslate_ui'):
                bench.retranslate_ui(target)

        # 3. Main window tree + dynamic pages (History, Collections, For You, Smart Resume)
        translate_widget_tree(win, target)

        hist = getattr(win, 'history_page', None)
        if hist is not None and hasattr(hist, 'refresh_view'):
            hist.refresh_view()
            translate_widget_tree(hist, target)

        coll = getattr(win, 'collections_page', None)
        if coll is not None and hasattr(coll, 'refresh_all'):
            coll.refresh_all()
            if hasattr(coll, 'refresh_folders_ui'):
                coll.refresh_folders_ui()
            translate_widget_tree(coll, target)

        fy = getattr(win, 'foryou_page', None)
        if fy is not None and hasattr(fy, 'retranslate_ui'):
            fy.retranslate_ui(target)

        if getattr(win, 'current_media_item', None) is None and hasattr(win, '_restore_passive_last_played_ui'):
            win._restore_passive_last_played_ui()

        # 4. Owned floating panels & popups
        sub_panel = getattr(win, 'subsettings_panel', None)
        if sub_panel is not None:
            if hasattr(sub_panel, 'retranslate_ui'):
                sub_panel.retranslate_ui(target)
            else:
                translate_widget_tree(sub_panel, target)

        for attr in ('mini_player', 'vol_popup'):
            sub_w = getattr(win, attr, None)
            if sub_w is not None:
                translate_widget_tree(sub_w, target)
        pb = getattr(win, 'playback_bar', None)
        if pb is not None and getattr(pb, 'info_popup', None) is not None:
            translate_widget_tree(pb.info_popup, target)


def install_app_language_manager(window: QWidget, settings: QSettings | None = None) -> AppLanguageManager:
    existing = getattr(window, '_language_manager', None)
    if isinstance(existing, AppLanguageManager):
        return existing
    mgr = AppLanguageManager(window, settings=settings)
    window._language_manager = mgr
    return mgr
