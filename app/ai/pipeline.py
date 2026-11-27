import os
import sys
import gc
import time
import re
from pathlib import Path
from typing import Callable, Optional, Dict
from PySide6.QtCore import QSettings

os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"

# ================================================================
# 🔥 FIX NVIDIA DLL (LAZY: gọi khi cần)
# ================================================================
def fix_nvidia_dlls():
    current_file_path = os.path.abspath(__file__)
    current_dir = os.path.dirname(current_file_path)
    app_root = os.path.dirname(os.path.dirname(current_dir))
    portable_libs = os.path.join(app_root, "app_resources", "libs")
    
    # Kích hoạt ghim thư mục DLL hệ thống cho Windows
    if os.path.exists(portable_libs):
        paths_to_check = [
            os.path.join(portable_libs, "ctranslate2"),
            os.path.join(portable_libs, "torch", "lib")
        ]
        for p in paths_to_check:
            if os.path.exists(p):
                try:
                    os.add_dll_directory(p)
                except Exception:
                    pass
                os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")

# ================================================================
# LIGHTWEIGHT IMPORTS (chỉ bản nhẹ)
# ================================================================
import difflib
from pipeline.extractor import extract_audio
from pipeline.lyric_refinement import refine_lyrics, finalize_cue_times, mark_final_timing
from pipeline.asr_coverage import repair_missing_subtitles
from pipeline.asr_intro_guard import audit_primary_intro
from pipeline.lyric_formatter import export_srt, export_lrc
from pipeline.jp_normalizer import normalize_japanese, universal_text_reconstruct

from subtitle.converter import refined_to_subtitles
from subtitle.storage import save_subtitles
from subtitle.mode import SubtitleMode
from subtitle.config import SubtitleConfig
from pipeline.utils import TempFileManager,is_connected
from pipeline.lyric_corrector import correct_raw_segments_online
# ================================================================
# 🔹 HELPERS
# ================================================================
def _check_cancel(cancel_cb):
    if cancel_cb and cancel_cb():
        raise RuntimeError("AI cancelled by user")

def _report(progress_cb, percent: int, msg: str):
    if progress_cb:
        progress_cb(percent, msg)


def _fmt_mmss(seconds: float) -> str:
    total = max(0, int(seconds))
    m, s = divmod(total, 60)
    return f"{m:02d}:{s:02d}"


def _consume_segments_with_progress(segments_generator, wav_duration, progress_cb, cancel_cb):
    """Stream Whisper segments with live 30%..50% progress & immediate cancel responsiveness."""
    segments_list = []
    monotonic = getattr(time, "monotonic", None)
    last_emit = 0.0
    for seg in segments_generator:
        _check_cancel(cancel_cb)
        segments_list.append(seg)
        if progress_cb:
            now = monotonic() if callable(monotonic) else (last_emit + 0.35)
            if now - last_emit >= 0.35:
                last_emit = now
                seg_end = float(getattr(seg, "end", 0.0) or 0.0)
                if wav_duration and wav_duration > 0:
                    ratio = min(1.0, max(0.0, seg_end / wav_duration))
                    pct = 30 + int(ratio * 20)
                    _report(
                        progress_cb,
                        pct,
                        f"📝 Nhận diện lời: {_fmt_mmss(seg_end)} / {_fmt_mmss(wav_duration)} · {len(segments_list)} câu",
                    )
                else:
                    _report(progress_cb, 38, f"📝 Nhận diện lời: {len(segments_list)} câu...")
    return segments_list
        
# Hàm làm sạch tên file
def sanitize_filename(name):
    # Loại bỏ các ký tự cấm của Windows: < > : " / \ | ? *
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()

# Cấu hình cho các nhóm ngôn ngữ khác nhau
LANG_CONFIG = {
    "cjk": ["ja", "zh", "ko"],  # Chữ tượng hình (không dấu cách)
    "latin": ["en", "vi", "fr", "de", "es", "it"] # Chữ Latin (có dấu cách)
}

# ================================================================
# ✅ PIPELINE CHUẨN
# ================================================================
def run_ai_pipeline(
    input_path: str,
    output_dir: str,
    media_id: str,
    progress_cb: Optional[Callable[[int, str], None]] = None,
    cancel_cb: Optional[Callable[[], bool]] = None,
    device_policy: str = "auto",
    translate_mode = None
) -> Dict:
    
    # 🔥 FIX NVIDIA DLLS (LAZY CALL - chỉ gọi khi AI thực sự chạy)
    fix_nvidia_dlls()

    from translate.pipeline import TranslateMode

    # Set default translate_mode nếu chưa có
    if translate_mode is None:
        translate_mode = TranslateMode.PIVOT_VI

    # --- BƯỚC KẾT NỐI SETTING: Đọc từ Registry ---
    settings = QSettings("MyStudio", "AI_Music_Player")
    from pipeline.content_mode import resolve_content_mode, DIALOGUE
    content_mode = resolve_content_mode(settings.value("subtitle_content_mode", "lyrics"))
    dialogue = content_mode == DIALOGUE

    raw_fast_lyrics = settings.value("fast_lyrics_enabled", "Bật (Siêu tốc)")
    if isinstance(raw_fast_lyrics, bool):
        fast_lyrics_enabled = raw_fast_lyrics
    else:
        fast_lyrics_str = str(raw_fast_lyrics or "Bật (Siêu tốc)").strip().lower()
        fast_lyrics_enabled = not (fast_lyrics_str.startswith("tắt") or fast_lyrics_str in {"0", "false", "off", "no"})

    # Nếu chưa có gì, mặc định dùng "medium" cho an toàn (vì large-v3 nặng 3GB RAM)
    saved_model = settings.value("ai_model", "medium")

    # Nếu chưa có gì, mặc định dùng "cpu" để tránh lỗi Driver NVIDIA chưa cài
    saved_device = settings.value("device", "cpu")

    # Mặc định là Local, không tốn tiền, không cần mạng
    online_provider = settings.value("online_provider", "Local Default")
    api_key = settings.value("api_key", "").strip()
    # ----------------------------------------------

    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    song_title_raw = input_path.stem

    current_file_path = os.path.abspath(__file__)
    current_dir = os.path.dirname(current_file_path)
    app_root = os.path.dirname(os.path.dirname(current_dir))
    local_model_path = os.path.join(app_root, "app_resources", "whisper_models", saved_model)
    fallback_model_path = os.path.join(app_root, "app_resources", "whisper_models", "medium")

    temp_wav_path = None
    lrclib_reference_lyric = None
    lrclib_reference_candidates = []
    lrc_vad_probe = None
    wav_duration = None
    used_fast_lyrics = False
    final_segments = None
    word_pool_for_karaoke = []
    detected_lang = "en"
    coverage = {}
    try:
        # ============================================================
        # 0️⃣ FAST-PATH PRE-ASR WATERFALL (Sidecar / Embedded / Parallel LRCLIB)
        # ============================================================
        if fast_lyrics_enabled:
            from pipeline.fast_lyrics import (
                find_sidecar_subtitle,
                probe_video_duration_and_embedded,
            )
            _report(progress_cb, 4, "⚡ Kiểm tra phụ đề có sẵn...")
            _check_cancel(cancel_cb)
            # Single ffprobe only for video containers; 0 ffprobe for audio-only files!
            media_duration, embedded_hit = probe_video_duration_and_embedded(input_path)
            local_hit = find_sidecar_subtitle(input_path, media_duration=media_duration)
            if local_hit is None:
                local_hit = embedded_hit
            if local_hit is not None:
                final_segments = local_hit["cues"]
                detected_lang = local_hit["language"]
                used_fast_lyrics = True
                print(
                    f"⚡ Fast-Path ({local_hit['source']}): nạp sẵn {len(final_segments)} dòng "
                    f"({detected_lang}), bỏ qua Whisper!"
                )
                _report(progress_cb, 55, f"⚡ Nạp nhanh phụ đề có sẵn ({len(final_segments)} dòng)")

        if not used_fast_lyrics:
            # ============================================================
            # 1️⃣ EXTRACT AUDIO SONG SONG VỚI TRA CỨU LRCLIB (0 ms độ trễ mạng!)
            # ============================================================
            should_query_lrclib = bool(fast_lyrics_enabled and not dialogue and is_connected())
            _report(
                progress_cb,
                8,
                "🎧 Trích xuất audio & tra cứu LRCLIB song song..." if should_query_lrclib else "🎧 Trích xuất audio...",
            )
            _check_cancel(cancel_cb)

            temp_wav_path = TempFileManager.create_unique_path()
            lrc_fetch_result = ([], "", "skipped")

            if should_query_lrclib:
                from concurrent.futures import ThreadPoolExecutor
                from pipeline.fast_lyrics import fetch_lrclib_items
                pool = ThreadPoolExecutor(max_workers=2)
                try:
                    fut_extract = pool.submit(extract_audio, str(input_path), str(temp_wav_path))
                    fut_lrclib = pool.submit(
                        fetch_lrclib_items,
                        song_title_raw,
                        timeout=2.0,
                        cancel_cb=cancel_cb,
                    )
                    success = fut_extract.result()
                    try:
                        # Never block Whisper beyond 1.2s extra after FFmpeg finishes
                        lrc_fetch_result = fut_lrclib.result(timeout=1.2)
                    except Exception:
                        lrc_fetch_result = ([], "", "timeout")
                finally:
                    pool.shutdown(wait=False, cancel_futures=True)
            else:
                success = extract_audio(str(input_path), str(temp_wav_path))

            if not success:
                raise RuntimeError("Lỗi trích xuất âm thanh (FFmpeg failed)")

            from pipeline.fast_lyrics import probe_media_duration
            wav_duration = probe_media_duration(temp_wav_path)

            # Đánh giá kết quả LRCLIB (nếu đã lấy được ứng viên) — xác thực kép Silero VAD
            lrc_items, lrc_eff_query, lrc_reason = lrc_fetch_result
            if should_query_lrclib and lrc_items:
                from pipeline.fast_lyrics import evaluate_lrclib_items
                has_close_synced = bool(
                    wav_duration
                    and any(
                        isinstance(it, dict)
                        and it.get("syncedLyrics")
                        and not it.get("instrumental")
                        and it.get("duration")
                        and abs(float(it["duration"]) - float(wav_duration)) <= 2.0
                        for it in lrc_items[:6]
                    )
                )
                if has_close_synced:
                    _report(progress_cb, 12, "🔎 Xác thực mốc giọng hát LRCLIB...")
                _check_cancel(cancel_cb)
                can_cuda_align_lrc = bool(
                    saved_device == "cuda"
                    and device_policy != "cpu"
                    and os.path.exists(local_model_path)
                    and os.path.exists(os.path.join(local_model_path, "model.bin"))
                )
                lrc_res = evaluate_lrclib_items(
                    song_title_raw,
                    lrc_items,
                    effective_query=lrc_eff_query,
                    fetch_reason=lrc_reason,
                    media_duration=wav_duration,
                    wav_path=temp_wav_path,
                    refine_ends_with_vad=not can_cuda_align_lrc,
                    allow_mv_offset=can_cuda_align_lrc,
                )
                lrclib_reference_lyric = lrc_res.get("plain_lyrics")
                lrclib_reference_candidates = lrc_res.get("plain_candidates") or (
                    [lrclib_reference_lyric] if lrclib_reference_lyric else []
                )
                lrc_vad_probe = lrc_res.get("vad_probe")
                requires_strict_fa = bool(lrc_res.get("requires_strict_fa"))
                if lrc_res.get("synced_cues"):
                    final_segments = lrc_res["synced_cues"]
                    detected_lang = lrc_res.get("language") or "en"
                    used_fast_lyrics = True
                    vinfo = lrc_res.get("verification") or {}
                    print(
                        f"⚡ Fast-Path (LRCLIB dual-verified): khớp chuẩn {len(final_segments)} câu "
                        f"({detected_lang}, onset_diff={vinfo.get('onset_diff')}s, "
                        f"voiced={vinfo.get('voiced_ratio')}), bỏ qua Whisper ASR!"
                    )
                    # Căn mốc kết thúc câu chuẩn từng từ bằng Forced Alignment trên CUDA (~2-3s, không decode)
                    fa_applied = False
                    if can_cuda_align_lrc:
                        fa_model = None
                        try:
                            _report(progress_cb, 35, "⏱ Căn chuẩn mốc kết thúc lời hát...")
                            _check_cancel(cancel_cb)
                            import torch as _fa_torch
                            if hasattr(_fa_torch, "cuda") and _fa_torch.cuda.is_available():
                                from faster_whisper import WhisperModel as _FAWhisperModel
                                from pipeline.lyric_timing import align_lrc_ends
                                fa_model = _FAWhisperModel(
                                    local_model_path,
                                    device="cuda",
                                    compute_type="float16",
                                    local_files_only=True,
                                )
                                aligned_lrc, fa_rep = align_lrc_ends(
                                    fa_model,
                                    temp_wav_path,
                                    detected_lang,
                                    final_segments,
                                    duration=wav_duration,
                                    spacer_flags=lrc_res.get("spacer_flags"),
                                    strict_mv=requires_strict_fa,
                                    cancel_cb=cancel_cb,
                                    budget_s=12.0,
                                    progress_cb=progress_cb,
                                )
                                if fa_rep.get("errors", 0) == 0 and fa_rep.get("sync_verified") is False:
                                    # Forced alignment proved LRCLIB does not match this recording's real timing!
                                    print(
                                        f"⚠️ Lời LRCLIB lệch nhịp thực tế ({fa_rep.get('reject_reason')}), "
                                        "tự động chuyển sang Whisper ASR!"
                                    )
                                    used_fast_lyrics = False
                                    final_segments = []
                                    fa_applied = True
                                elif fa_rep.get("errors", 0) == 0 and aligned_lrc:
                                    final_segments = aligned_lrc
                                    fa_applied = True
                                    from pipeline.word_karaoke import collect_fa_word_pool
                                    word_pool_for_karaoke = collect_fa_word_pool(
                                        fa_rep.get("word_candidates"),
                                        cues=aligned_lrc,
                                    )
                                    print(
                                        f"⏱ Căn mốc Fast-Path (CUDA): {fa_rep['changed']}/{len(final_segments)} câu, "
                                        f"shift={fa_rep.get('global_shift', 0.0):+.2f}s, mad={fa_rep.get('median_abs_residual', 0.0):.2f}s, "
                                        f"{fa_rep['windows']} cửa sổ, {fa_rep['seconds']:.2f}s."
                                    )
                        except Exception as fa_err:
                            _check_cancel(cancel_cb)
                            print(f"⚠️ Căn mốc kết thúc CUDA gặp lỗi ({fa_err}), dùng Silero VAD fallback.")
                        finally:
                            if fa_model is not None:
                                del fa_model
                            gc.collect()
                            _t_mod = sys.modules.get("torch")
                            if _t_mod is not None and hasattr(_t_mod, "cuda") and _t_mod.cuda.is_available():
                                _t_mod.cuda.empty_cache()
                    if requires_strict_fa and not fa_applied:
                        # Coarse-shifted MVs MUST pass strict CUDA FA; never trust unverified coarse offsets.
                        used_fast_lyrics = False
                        final_segments = []
                    if used_fast_lyrics:
                        if not fa_applied and can_cuda_align_lrc:
                            from pipeline.fast_lyrics import refine_lrc_ends_with_audio
                            final_segments = refine_lrc_ends_with_audio(
                                final_segments,
                                temp_wav_path,
                                media_duration=wav_duration,
                                spacer_flags=lrc_res.get("spacer_flags"),
                            )
                        _report(progress_cb, 60, f"⚡ Khớp chuẩn lời LRCLIB ({len(final_segments)} câu)")

        if not used_fast_lyrics:
            # Báo trạng thái TRƯỚC khi import torch / faster_whisper để thanh tiến trình không kẹt ở bước cũ!
            _report(progress_cb, 15, f"🧠 Đang nạp động cơ AI ({saved_model})...")
            _check_cancel(cancel_cb)

            # 🔥 IMPORT NẶNG CHỈ KHI THỰC SỰ CẦN CHẠY WHISPER
            import torch
            from faster_whisper import WhisperModel

            # ============================================================
            # 2️⃣ LOAD WHISPER MODEL (ĐÃ THÁO XÍCH MẠNG KHI FALLBACK CPU)
            # ============================================================
            _report(progress_cb, 20, f"🧠 Nạp Whisper ({saved_model})")
            _check_cancel(cancel_cb)

            model = None
            try:
                has_cuda = False
                try: has_cuda = torch.cuda.is_available()
                except AttributeError: has_cuda = False

                actual_device = "cuda" if saved_device == "cuda" and has_cuda else "cpu"
                compute_type = "float16" if actual_device == "cuda" else "int8"

                if device_policy == "cpu":
                    raise RuntimeError("Force CPU")

                # Trường hợp 1: Có file offline local -> Khóa mạng, chạy offline hoàn toàn
                if os.path.exists(local_model_path) and os.path.exists(os.path.join(local_model_path, "model.bin")):
                    print(f"⚡ Đang chạy Model từ nguồn Local tuyệt đối: {local_model_path}")
                    model = WhisperModel(
                        local_model_path,
                        device=actual_device,
                        compute_type=compute_type,
                        local_files_only=True
                    )
                else:
                    # Trường hợp 2: Local trống -> Mở xích mạng tạm thời để tải tự động hoặc đọc cache hệ thống
                    print(f"🌐 Sẵn sàng đồng bộ trực tuyến cho model: {saved_model}")
                    os.environ["HF_HUB_OFFLINE"] = "0" # Mở khóa mạng
                    os.environ["TRANSFORMERS_OFFLINE"] = "0"

                    model = WhisperModel(
                        saved_model,
                        device=actual_device,
                        compute_type=compute_type,
                        local_files_only=False
                    )

            except Exception as e:
                print(f"⚠️ Luồng chính lỗi, kích hoạt Fallback CPU cứu vãn: {e}")

                # Mở khóa mạng tối đa để chế độ CPU có thể tự kết nối tải file cứu app
                os.environ["HF_HUB_OFFLINE"] = "0"
                os.environ["TRANSFORMERS_OFFLINE"] = "0"

                if os.path.exists(fallback_model_path) and os.path.exists(os.path.join(fallback_model_path, "model.bin")):
                    model = WhisperModel(fallback_model_path, device="cpu", compute_type="int8", local_files_only=True)
                else:
                    print("📡 Đang tải tự động model 'medium' từ Hugging Face về máy qua CPU...")
                    model = WhisperModel("medium", device="cpu", compute_type="int8", local_files_only=False)
            # ============================================================
            # 3️⃣ TRANSCRIBE
            # ============================================================
            _report(progress_cb, 30, "📝 Nhận diện lời nói")
            _check_cancel(cancel_cb)

            song_title = input_path.stem.replace("_", " ").replace("-", " ")

            prompt_text = " .+"

            try:
                # Truyền file temp_wav_path vào
                if dialogue:
                    from pipeline.dialogue import transcription_options
                    segments_generator, info = model.transcribe(
                        str(temp_wav_path), **transcription_options())
                else:
                    segments_generator, info = model.transcribe(
                        str(temp_wav_path),
                        language=None,
                        word_timestamps=True,
                        condition_on_previous_text=False,
                        beam_size=3,
                        temperature=0.0,
                        vad_filter=False,
                        vad_parameters=dict(min_silence_duration_ms=1000),
                        initial_prompt= prompt_text
                    )
                detected_lang = info.language
                print(f"📡 Ngôn ngữ phát hiện: {detected_lang} ({info.language_probability*100:.1f}%)")
                _report(progress_cb, 30, f"📝 Nhận diện lời ({detected_lang.upper()})...")
                segments_list = _consume_segments_with_progress(
                    segments_generator, wav_duration, progress_cb, cancel_cb
                )
                language_probability = getattr(info, "language_probability", 0.0)

            except Exception as e:
                # Xử lý lỗi tràn VRAM
                if "cuda" in str(e).lower():
                    print("⚠️ Lỗi VRAM, thử lại bằng CPU...")
                    _report(progress_cb, 26, "⚠️ Tràn VRAM, chuyển sang CPU...")
                    del model
                    torch.cuda.empty_cache()
                    model = WhisperModel(fallback_model_path if os.path.isfile(os.path.join(fallback_model_path, "model.bin"))
                                         else "medium", device="cpu", compute_type="int8")
                    # Chạy lại với file temp
                    from pipeline.lyric_accuracy import primary_options
                    if dialogue:
                        from pipeline.dialogue import transcription_options
                        segments_generator, fallback_info = model.transcribe(
                            str(temp_wav_path), **transcription_options())
                    else:
                        segments_generator, fallback_info = model.transcribe(str(temp_wav_path), **primary_options())
                    segments_list = _consume_segments_with_progress(
                        segments_generator, wav_duration, progress_cb, cancel_cb
                    )
                    detected_lang = fallback_info.language
                    language_probability = getattr(fallback_info, "language_probability", 0.0)
                else:
                    raise e

            # Independent first-window sanity check. The full-song primary decode
            # above is kept unchanged for normal songs; only a long instrumental
            # intro can trigger filtering or a strongly justified language re-run.
            intro_report = {}
            if not dialogue:
                _report(progress_cb, 52, "🛡 Kiểm tra đoạn đầu bài...")
                segments_list, detected_lang, intro_report = audit_primary_intro(
                    model,
                    temp_wav_path,
                    segments_list,
                    detected_lang,
                    language_probability,
                    cancel_cb=cancel_cb,
                    prefetched_probe=lrc_vad_probe,
                )
            if intro_report.get("removed"):
                first_voice = intro_report.get("first_voice")
                voice_note = f" (giọng đầu ~{first_voice:.2f}s)" if isinstance(first_voice, (int, float)) else ""
                print(
                    f"🛡 Intro guard: bỏ {len(intro_report['removed'])} đoạn ASR không được xác minh{voice_note}."
                )
            if intro_report.get("empty_intro_recovered"):
                print(
                    f"🛡 Intro guard: cứu được {intro_report.get('empty_intro_added', 0)} đoạn đầu bài bị bỏ sót "
                    f"(giọng đầu ~{intro_report.get('empty_intro_first_voice')}s)."
                )
            if intro_report.get("language_rerun"):
                print(
                    "🌐 Kiểm tra lại ngôn ngữ từ đoạn có giọng: "
                    f"{intro_report.get('language_before')} → {intro_report.get('language_after')}."
                )
            if intro_report.get("error"):
                print(f"⚠️ Bỏ qua kiểm tra intro, giữ nguyên ASR chính: {intro_report['error']}")
            if intro_report.get("language_probe_error"):
                print(
                    "⚠️ Không kiểm tra lại được ngôn ngữ intro; giữ nguyên ASR chính: "
                    f"{intro_report['language_probe_error']}"
                )
            if intro_report.get("language_rerun_rejected"):
                print("⚠️ Bỏ kết quả nhận diện lại ngôn ngữ vì rỗng; giữ nguyên ASR chính.")
            if intro_report.get("verification_error"):
                print(
                    "⚠️ Không xác minh được chữ ở intro; giữ nguyên các câu ASR thường: "
                    f"{intro_report['verification_error']}"
                )

            _check_cancel(cancel_cb)

            # ============================================================
            # 4️⃣ PRE-PROCESSING (XỬ LÝ THÔNG MINH AN TOÀN)
            # ============================================================
            _report(progress_cb, 50, f"🧹 Làm sạch dữ liệu ({detected_lang})")

            raw_segments = []
            for s in segments_list:
                if dialogue:
                    processed_text = s.text.strip()
                elif s.words:
                    processed_text = universal_text_reconstruct(s.words, s.text)
                else:
                    processed_text = s.text.strip()

                if not processed_text: continue

                words_data = []
                if s.words:
                    words_data = [{"start": w.start, "end": w.end, "word": w.word} for w in s.words]

                raw_segments.append({
                    "start": s.start,
                    "end": s.end,
                    "text": processed_text,
                    "words": words_data,
                })

            from pipeline.word_karaoke import collect_fa_word_pool, collect_whisper_word_pool
            word_pool_for_karaoke = collect_whisper_word_pool(raw_segments)

            # ============================================================
            # 5️⃣ REFINE SEGMENTS & EXPORT RAW
            # ============================================================
            _report(progress_cb, 55, "✂️ Căn chỉnh subtitle")
            _check_cancel(cancel_cb)

            is_cjk = detected_lang in LANG_CONFIG["cjk"]

            if dialogue:
                from pipeline.dialogue import refine_dialogue
                final_segments = refine_dialogue(raw_segments, cjk=is_cjk)
            else:
                final_segments = refine_lyrics(
                    raw_segments,
                    max_chars=22 if is_cjk else 74,
                    min_pause=0.54 if is_cjk else 0.6,
                    start_offset=-0.2 if is_cjk else 0,
                    end_padding=0.27 if is_cjk else 0.6,
                    gap_threshold=0.6,
                    memory_reset_t=3.0
                )

            try:
                if not dialogue:
                    final_segments, coverage = repair_missing_subtitles(
                        model, temp_wav_path, detected_lang, final_segments,
                        dict(max_chars=22 if is_cjk else 74, min_pause=0.54 if is_cjk else 0.6,
                             start_offset=-0.2 if is_cjk else 0, end_padding=0.27 if is_cjk else 0.6,
                             gap_threshold=0.6, memory_reset_t=3.0),
                        cancel_cb=cancel_cb, progress_cb=progress_cb, refine_fn=refine_lyrics,
                        boundary_gap=0.0, boundary_tolerance=0.08,
                        primary_segments=segments_list,
                        prefetched_speech=intro_report.get("confirmed_speech"))
                    print(f"🛠 Kiểm tra coverage: thêm {coverage.get('added_cues', 0)} dòng, "
                          f"{len(coverage.get('attempts', []))} lượt nhận diện lại.")
                    if coverage.get("unresolved_speech"):
                        print(f"⚠️ Vùng có giọng nghi thiếu lời, cần kiểm tra: {coverage['unresolved_speech']}")
                    if coverage.get("error"):
                        print(f"⚠️ Nhận diện bổ sung gặp lỗi: {coverage['error']}")
                    if coverage.get("verification_errors"):
                        print(
                            f"⚠️ Bỏ {len(coverage['verification_errors'])} kết quả recovery "
                            "vì lượt xác minh độc lập bị lỗi."
                        )
                    from pipeline.lyric_timing import align_lyric_onsets
                    _check_cancel(cancel_cb)
                    _report(progress_cb, 58, "⏱ Căn mốc lời hát...")
                    final_segments, timing_report = align_lyric_onsets(
                        model, temp_wav_path, detected_lang, final_segments,
                        cancel_cb=cancel_cb, progress_cb=progress_cb)
                    if timing_report.get("word_candidates"):
                        word_pool_for_karaoke = collect_fa_word_pool(
                            timing_report.get("word_candidates"),
                            fallback_pool=word_pool_for_karaoke,
                            cues=final_segments,
                        )
                    print(f"⏱ Căn mốc local: {timing_report['changed']} câu, "
                          f"{timing_report['windows']} cửa sổ, {timing_report['seconds']:.2f}s.")
                    if timing_report["errors"] or timing_report["capped"]:
                        print("ℹ️ Căn mốc chưa hoàn tất; các câu còn lại giữ thời gian ASR cũ.")
            except Exception as error:
                _check_cancel(cancel_cb)
                print(f"⚠️ Không kiểm tra được coverage bổ sung: {error}")
            finally:
                del model
                gc.collect()
                if hasattr(torch, "cuda") and torch.cuda.is_available():
                    torch.cuda.empty_cache()

            # Display margins belong after coverage, so they never change which
            # vocal gaps trigger recovery or which recovered words are accepted.
            from pipeline.lyric_refinement import finalize_display_times
            from pipeline.fast_lyrics import close_flicker_micro_gaps
            if not dialogue:
                final_segments = close_flicker_micro_gaps(
                    finalize_display_times(
                        final_segments, cjk=is_cjk, duration=coverage.get("duration")),
                    min_clean_gap=0.52,
                )
                if final_segments and lrclib_reference_candidates:
                    from pipeline.lyric_reference_snap import snap_asr_cues_to_reference
                    final_segments, snap_rep = snap_asr_cues_to_reference(
                        final_segments,
                        lrclib_reference_candidates,
                        lang=detected_lang,
                    )
                    if snap_rep.get("snapped_cues", 0) > 0:
                        if snap_rep.get("selected_lyrics"):
                            lrclib_reference_lyric = snap_rep["selected_lyrics"]
                        sel_track = snap_rep.get("selected_track") or "LRCLIB"
                        print(
                            f"✨ Chuẩn hóa lời gốc theo tham chiếu ({sel_track}): "
                            f"gắn chuẩn {snap_rep['snapped_cues']}/{snap_rep['total_cues']} câu "
                            f"(giữ nguyên 100% mốc giờ Whisper, mode={snap_rep.get('mode')})."
                        )
            _check_cancel(cancel_cb)

        # Xuất file SRT/LRC ra thư mục Output của người dùng
        base_name = input_path.stem
        clean_name = sanitize_filename(base_name)
        
        # Tạo thư mục con nếu chưa có
        (output_dir / "subtitles" / "source" / "srt").mkdir(parents=True, exist_ok=True)
        (output_dir / "subtitles" / "source" / "lrc").mkdir(parents=True, exist_ok=True)

        export_srt(final_segments, output_dir / "subtitles" / "source" / "srt" / f"{clean_name}.srt")
        export_lrc(final_segments, output_dir / "subtitles" / "source" / "lrc" / f"{clean_name}.lrc")

        if not final_segments:
            # A completed recognition pass can legitimately contain no lyrics.
            # Keep the usual result/export contracts, without loading translators.
            if media_id:
                from pipeline.word_karaoke import save_word_timings
                save_word_timings(output_dir / "subtitles" / "words", str(media_id), [])
            _check_cancel(cancel_cb)
            _report(progress_cb, 100, "ℹ️ Hoàn tất: chưa nhận diện được lời (có thể là nhạc không lời).")
            return {"media_id": media_id, "segments": []}

        # ============================================================
        # 6️⃣ TRANSLATE (ĐIỀU HƯỚNG CHUẨN: USER LÀ NHẤT)
        # ============================================================
        from translate.pipeline import translate_pipeline, clear_translator
        from translate.online_logic import translate_online_pipeline
        
        # Chuyển đổi sang object Subtitle
        subs = refined_to_subtitles(final_segments, lang=detected_lang)
        
        _report(progress_cb, 70, "🌍 Đang chuẩn bị dịch thuật...")
        _check_cancel(cancel_cb)

        if detected_lang == "vi":
            print("🇻🇳 Tiếng Việt: Giữ nguyên gốc")
        else:
            # --- LUỒNG ĐIỀU HƯỚNG MỚI ---
            
            # TRƯỜNG HỢP 1: USER CHỌN ONLINE (VÀ CÓ KEY)
            if online_provider != "Local Default" and api_key:
                _report(progress_cb, 75, f"🌐 Đang dịch Online ({online_provider})...")
                
                if is_connected():
                    # Gọi thẳng Online Logic
                    result = translate_online_pipeline(
                        subs,
                        online_provider,
                        api_key,
                        song_title_raw=song_title_raw,
                        content_mode=content_mode,
                        extra_reference_lyric=lrclib_reference_lyric,
                    )
                    if result:
                        subs = result
                        print(f"✅ Dịch Online ({online_provider}) hoàn tất.")
                    else:
                        # Nếu Online lỗi (mạng/API), tự động về Local để cứu vãn
                        _report(progress_cb, 80, "⚠️ Online lỗi. Tự động Fallback về Local...")
                        subs = translate_pipeline(subs, provider="Local Default", src_lang=detected_lang, mode=translate_mode)
                else:
                    _report(progress_cb, 80, "⚠️ Mất kết nối mạng. Đang dùng Local...")
                    subs = translate_pipeline(subs, provider="Local Default", src_lang=detected_lang, mode=translate_mode)

            # TRƯỜNG HỢP 2: USER CHỌN LOCAL (HOẶC CHƯA NHẬP KEY)
            else:
                _report(progress_cb, 85, "💻 Đang dịch bằng Local NLLB (Cố định)...")
                # Truyền provider="Local Default" để hàm bên trong biết mà chặn đứng Cloud API
                subs = translate_pipeline(
                    subs, 
                    provider="Local Default", 
                    src_lang=detected_lang, 
                    mode=translate_mode
                )

        # Giải phóng bộ nhớ
        clear_translator()
        gc.collect()
        torch_mod = sys.modules.get("torch")
        if torch_mod is not None and hasattr(torch_mod, "cuda") and torch_mod.cuda.is_available():
            torch_mod.cuda.empty_cache()

        # ============================================================
        # 7️⃣ KẾT THÚC
        # ============================================================
        _report(progress_cb, 100, "✅ Hoàn tất AI")
        mark_final_timing(subs)
        if media_id:
            try:
                from pipeline.word_karaoke import extract_and_align_cue_words, save_word_timings
                word_entries = extract_and_align_cue_words(subs, word_pool_for_karaoke)
                save_word_timings(output_dir / "subtitles" / "words", str(media_id), word_entries)
            except Exception as wk_err:
                print(f"⚠️ Không thể lưu mốc karaoke từng từ (giữ nguyên phụ đề chính): {wk_err}")
        #serialized_result = _serialize_subtitles(subs)
        return {
            "media_id": media_id,
            "segments": subs
        }

    except Exception as e:
        # Nếu có lỗi thì ném ra ngoài để Worker bắt
        raise e

    finally:
        # 🔥 VÙNG AN TOÀN TUYỆT ĐỐI 🔥
        # Dù thành công hay thất bại, file wav tạm luôn bị xóa
        if temp_wav_path:
            TempFileManager.safe_delete(temp_wav_path)
