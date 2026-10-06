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
    
    # 🔥🔥🔥 IMPORT NẶNG TẠI ĐÂY (LAZY IMPORT) 🔥🔥🔥
    # Những library này chỉ được nạp khi user thực sự nhấn nút "Tạo AI"
    # Giúp app startup nhanh 30 giây!
    import torch
    from faster_whisper import WhisperModel
    import lyricsgenius
    from subtitle.ass.renderer import render_ass
    from translate.pipeline import TranslateMode
    
    # Set default translate_mode nếu chưa có
    if translate_mode is None:
        translate_mode = TranslateMode.PIVOT_VI
    
    # --- BƯỚC KẾT NỐI SETTING: Đọc từ Registry ---
    settings = QSettings("MyStudio", "AI_Music_Player")
    
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
    try:
        # ============================================================
        # 1️⃣ EXTRACT AUDIO (DÙNG TEMP FILE MANAGER)
        # ============================================================
        _report(progress_cb, 5, "🎧 Trích xuất audio")
        _check_cancel(cancel_cb)

        # 🔥 CÁCH MỚI: Xin cấp phát 1 file tạm an toàn trong storage/temp_cache
        # Không cần lo đặt tên trùng lặp, không cần lo tạo folder thủ công
        temp_wav_path = TempFileManager.create_unique_path()

        # Gọi hàm tối ưu (đã ẩn cửa sổ đen CMD)
        success = extract_audio(str(input_path), str(temp_wav_path))
        if not success:
            raise RuntimeError("Lỗi trích xuất âm thanh (FFmpeg failed)")
        time.sleep(0.5)
        # ============================================================
        # 2️⃣ LOAD WHISPER MODEL (ĐÃ THÁO XÍCH MẠNG KHI FALLBACK CPU)
        # ============================================================
        _report(progress_cb, 15, f"🧠 Nạp Whisper ({saved_model})")
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
                #prompt_reset_on_temperature=0.5
                #log_prob_threshold=None,      # Ép AI nhận diện ngay cả khi âm thanh mờ nhạt
                #compression_ratio_threshold=2.4, # Cho phép nhạc dạo đầu lặp lại không bị coi là rác
                #no_speech_threshold=0.4        # Chấp nhận tiếng người nhỏ hơn nhạc nền
            )
            detected_lang = info.language
            print(f"📡 Ngôn ngữ phát hiện: {detected_lang} ({info.language_probability*100:.1f}%)")
            segments_list = list(segments_generator)
            language_probability = getattr(info, "language_probability", 0.0)
            
        except Exception as e:
            # Xử lý lỗi tràn VRAM
            if "cuda" in str(e).lower():
                print("⚠️ Lỗi VRAM, thử lại bằng CPU...")
                del model
                torch.cuda.empty_cache()
                model = WhisperModel(fallback_model_path if os.path.isfile(os.path.join(fallback_model_path, "model.bin"))
                                     else "medium", device="cpu", compute_type="int8")
                # Chạy lại với file temp
                from pipeline.lyric_accuracy import primary_options
                segments_generator, fallback_info = model.transcribe(str(temp_wav_path), **primary_options())
                segments_list = list(segments_generator)
                detected_lang = fallback_info.language
                language_probability = getattr(fallback_info, "language_probability", 0.0)
            else:
                raise e

        # Independent first-window sanity check. The full-song primary decode
        # above is kept unchanged for normal songs; only a long instrumental
        # intro can trigger filtering or a strongly justified language re-run.
        segments_list, detected_lang, intro_report = audit_primary_intro(
            model,
            temp_wav_path,
            segments_list,
            detected_lang,
            language_probability,
            cancel_cb=cancel_cb,
        )
        if intro_report.get("removed"):
            first_voice = intro_report.get("first_voice")
            voice_note = f" (giọng đầu ~{first_voice:.2f}s)" if isinstance(first_voice, (int, float)) else ""
            print(
                f"🛡 Intro guard: bỏ {len(intro_report['removed'])} đoạn ASR không được xác minh{voice_note}."
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
            # 🔥 SỬ DỤNG HÀM TÁI CẤU TRÚC
            # Bỏ qua s.text của Whisper (vì nó có thể bị dính hoặc sai format)
            # Tự xây lại câu từ s.words
            if s.words:
                processed_text = universal_text_reconstruct(s.words, s.text)
            else:
                processed_text = s.text.strip() # Fallback nếu xui xẻo không có words

            if not processed_text: continue

            # Chuẩn bị dữ liệu words cho bước aligner sau này
            words_data = []
            if s.words:
                words_data = [{"start": w.start, "end": w.end, "word": w.word} for w in s.words]

            raw_segments.append({
                "start": s.start,
                "end": s.end,
                "text": processed_text, 
                "words": words_data,
            })

                        
        # ============================================================
        # 5️⃣ REFINE SEGMENTS & EXPORT RAW
        # ============================================================
        _report(progress_cb, 55, "✂️ Căn chỉnh subtitle")
        _check_cancel(cancel_cb)

        # Keep the orchestration options compatible with legacy refinement.
        # The new profile uses its own 50 ms lead / 80 ms tail, not these offsets.
        is_cjk = detected_lang in LANG_CONFIG["cjk"]
        
        final_segments = refine_lyrics(
            raw_segments,
            max_chars=22 if is_cjk else 74,
            min_pause=0.54 if is_cjk else 0.6,
            start_offset=-0.2 if is_cjk else 0,
            end_padding=0.27 if is_cjk else 0.6,
            gap_threshold=0.6,
            memory_reset_t=3.0
        )

        coverage = {}
        try:
            final_segments, coverage = repair_missing_subtitles(
                model, temp_wav_path, detected_lang, final_segments,
                dict(max_chars=22 if is_cjk else 74, min_pause=0.54 if is_cjk else 0.6,
                     start_offset=-0.2 if is_cjk else 0, end_padding=0.27 if is_cjk else 0.6,
                     gap_threshold=0.6, memory_reset_t=3.0),
                cancel_cb=cancel_cb, progress_cb=progress_cb, refine_fn=refine_lyrics,
                boundary_gap=0.0, boundary_tolerance=0.08)
            print(f"🛠 Kiểm tra coverage: thêm {coverage.get('added_cues', 0)} dòng, "
                  f"{len(coverage.get('attempts', []))} lượt nhận diện lại.")
            if coverage.get("unresolved_speech"):
                print(f"⚠️ Vùng có giọng nghi thiếu lời, cần kiểm tra: {coverage['unresolved_speech']}")
            if coverage.get("error"):
                print(f"⚠️ Nhận diện bổ sung gặp lỗi: {coverage['error']}")
        except Exception as error:
            _check_cancel(cancel_cb)
            # Preserve primary recognition if optional local coverage detection fails.
            print(f"⚠️ Không kiểm tra được coverage bổ sung: {error}")
        finally:
            del model
            gc.collect()
            if hasattr(torch, "cuda") and torch.cuda.is_available():
                torch.cuda.empty_cache()

        final_segments = finalize_cue_times(final_segments, duration=coverage.get("duration"))
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
                        song_title_raw=song_title_raw
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
        if hasattr(torch, "cuda") and torch.cuda.is_available():
            torch.cuda.empty_cache()

        # ============================================================
        # 7️⃣ KẾT THÚC
        # ============================================================
        _report(progress_cb, 100, "✅ Hoàn tất AI")
        mark_final_timing(subs)
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
