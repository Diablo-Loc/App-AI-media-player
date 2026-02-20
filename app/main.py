import os
import glob
import sys
import torch
from pathlib import Path
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"
# ================================================================
# 🔥 ĐOẠN FIX LỖI DLL DÀNH RIÊNG CHO WINDOWS & RTX 4060
# ================================================================
def fix_nvidia_dlls():
    # Tìm đường dẫn đến site-packages trong venv
    for path in sys.path:
        if "site-packages" in path:
            nvidia_path = os.path.join(path, "nvidia")
            if os.path.exists(nvidia_path):
                # Danh sách các thư mục chứa file .dll
                bins = [
                    os.path.join(nvidia_path, "cublas", "bin"),
                    os.path.join(nvidia_path, "cudnn", "bin")
                ]
                for b in bins:
                    if os.path.exists(b):
                        print(f"✅ Đã tìm thấy thư viện: {b}")
                        # Ép Windows load DLL từ thư mục này (Dành cho Python 3.8+)
                        os.add_dll_directory(b)
                        # Hỗ trợ thêm cho các bản Python cũ hơn
                        os.environ["PATH"] = b + os.pathsep + os.environ["PATH"]

fix_nvidia_dlls()
# ================================================================

from faster_whisper import WhisperModel
from pipeline.extractor import extract_audio 
from pipeline.aligner import refine_segments 
from pipeline.lyric_formatter import export_srt, export_lrc
from pipeline.jp_normalizer import normalize_japanese
from subtitle.ass.renderer import render_ass
from translate.translator import NLLBTranslator
from subtitle.converter import refined_to_subtitles
from subtitle.storage import save_subtitles
from subtitle.model import SubtitleLine
from subtitle.mode import SubtitleMode
from subtitle.config import SubtitleConfig
from translate.pipeline import translate_pipeline,TranslateMode, clear_translator


def main():
    print("\n--- 🚀 KHỞI ĐỘNG HỆ THỐNG (BẢN FIX DLL) ---")
    
    input_files = glob.glob("input/*.mp4") + glob.glob("input/*.mkv") + glob.glob("input/*.mp3")
    if not input_files:
        print("❌ LỖI: Thư mục 'input' trống!"); return
        
    input_path = Path(input_files[0])
    audio_file = Path("output/audio.wav")
    audio_file.parent.mkdir(exist_ok=True)
    # 1. Trích xuất âm thanh
    if audio_file.exists(): os.remove(audio_file)
    extract_audio(str(input_path), str(audio_file))
    # 2. Nạp Model (Dùng CPU làm dự phòng nếu GPU vẫn lỗi DLL)
    print(f"--- 🤖 ĐANG NẠP AI... ---")
    try:
        model = WhisperModel("large-v3", device="cuda", compute_type="float16")
        print("⚡ Chế độ: GPU (RTX 4060)")
    except Exception as e:
        print(f"⚠️ GPU lỗi DLL: {e}")
        print("🐢 Đang chuyển sang chế độ: CPU (Vẫn ra kết quả tốt)")
        model = WhisperModel("medium", device="cpu", compute_type="int8")
    song_title = input_path.stem.replace("_", " ").replace("-", " ")
    #prompt_text = f"Lyrics: {song_title}. 歌詞. Subtitles. 🎵"
    prompt_text= ".+"
    # 3. Transcribe
    print("--- 🎧 AI ĐANG LẮNG NGHE... ---")
    segments_generator, info = model.transcribe(
        str(audio_file),
        language=None,
        word_timestamps=True,
        condition_on_previous_text=False,
        beam_size=3,
        temperature=0.0, 
        vad_filter=False,
        #vad_parameters=dict(min_silence_duration_ms=500),
        initial_prompt=prompt_text
    )
    # 5.Thu thập kết quả
    raw_segments = []
    try:
        segments_list = list(segments_generator)
        del model 
        import gc
        gc.collect()
        torch.cuda.empty_cache()
        for s in segments_list:
            
            words_data = []
            if s.words:
                for w in s.words:
                    words_data.append({"start": w.start, "end": w.end, "word": w.word})
                
                txt = s.text.strip()
                if txt:
                    raw_segments.append({
                        "start": s.start, # Đổi từ seg_start thành start
                        "end": s.end,     # Đổi từ seg_end thành end
                        "text": normalize_japanese(txt),
                        "words": words_data
                    })
                    
    except Exception as e:
        print(f"❌ Lỗi xử lý âm thanh: {e}")
    # 7. Xuất kết quả
    if raw_segments:
        print("--- ✨ ĐANG XUẤT FILE ---")
        final_segments = refine_segments(raw_segments, 
                                        max_chars=22, 
                                        min_pause=0.55, 
                                        start_offset=0.02, 
                                        end_padding=0.3)
        base_name = input_path.stem 
        export_srt(final_segments, f"output/{base_name}.srt")
        export_lrc(final_segments, f"output/{base_name}.lrc")
        print(f"✅ HOÀN THÀNH: {base_name}.lrc")
        # Mới thêm(subtitle)
        subs = refined_to_subtitles(final_segments, lang="ja")
        # --- BƯỚC DỊCH SONG NGỮ ---
        print("🌍 Đang bắt đầu dịch thuật (NLLB-200 Batch Mode)...")
        
        # Gọi pipeline để nó tự dịch và gán vào 'subs'
        subs = translate_pipeline(subs, mode=TranslateMode.PIVOT_VI)

        # Giải phóng bộ nhớ GPU sau khi dịch xong
        clear_translator()
        # ... sau khi dịch xong
        print(f"DEBUG: Số lượng subs sau dịch: {len(subs)}")
        if len(subs) > 0:
            print(f"DEBUG: Dòng đầu tiên - Top: {subs[0].top.text if subs[0].top else 'Rỗng'}")
            print(f"DEBUG: Dòng đầu tiên - Bottom: {subs[0].bottom.text if subs[0].bottom else 'Rỗng'}")

        # --- LƯU VÀ RENDER ---
        save_subtitles(subs, f"output/{base_name}.json") # Nên dùng base_name thay vì test_project
        # --- LƯU VÀ RENDER ---
        cfg = SubtitleConfig()
        render_ass(subs, f"output/{base_name}.ass", cfg, mode=SubtitleMode.JP_EN_VI)
        print(f"✅ HOÀN THÀNH FILE SONG NGỮ: {base_name}.ass")
    else:
        print("❌ AI không nhận diện được lời. Hãy thử kiểm tra file audio.wav")

if __name__ == "__main__":
    main()