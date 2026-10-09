"""Exact reviewed empty-result edits; preserve whole-module legacy AST gates."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDITS = {
    'app/ai/pipeline.py': [
        ('        if not final_segments:\n            raise RuntimeError("⚠️ Không tìm thấy lời thoại nào.")\n', ''),
        ('        export_lrc(final_segments, output_dir / "subtitles" / "source" / "lrc" / f"{clean_name}.lrc")\n',
         '''        export_lrc(final_segments, output_dir / "subtitles" / "source" / "lrc" / f"{clean_name}.lrc")

        if not final_segments:
            # A completed recognition pass can legitimately contain no lyrics.
            # Keep the usual result/export contracts, without loading translators.
            _check_cancel(cancel_cb)
            _report(progress_cb, 100, "ℹ️ Hoàn tất: chưa nhận diện được lời (có thể là nhạc không lời).")
            return {"media_id": media_id, "segments": []}
'''),
    ],
    'app/core/subtitle_manager.py': [
        ('        if not segments:\n            logger.warning("⚠️ AI trả về 0 segment")',
         '        if segments is None:\n            logger.warning("⚠️ AI không trả về dữ liệu subtitle")'),
        ('            self._save_json_file(json_path, final_json)',
         '            if self._save_json_file(json_path, final_json) is False:\n                return None'),
        ('                json.dump(data, f, ensure_ascii=False, indent=2)\n        except Exception as e:\n            logger.error(f"❌ Save JSON failed: {e}")',
         '                json.dump(data, f, ensure_ascii=False, indent=2)\n            return True\n        except Exception as e:\n            logger.error(f"❌ Save JSON failed: {e}")\n            return False'),
        ('        data = self.get_raw_data(media_id)\n        if not data:\n            return False',
         '        data = self.get_raw_data(media_id)\n        if not isinstance(data, dict) or not data:\n            return False'),
        ('        segments = data.get("segments", [])\n        if not segments:\n            return False',
         '        segments = data.get("segments")\n        if not isinstance(segments, list):\n            return False'),
        ('            return "[Events]" in text and "Dialogue:" in text',
         '''            if "[Events]" in text and "Dialogue:" in text:
                return True
            # A header-only ASS is valid only with an explicit saved empty list.
            # Do not turn missing, malformed or truncated subtitle data into a
            # cached 'no lyrics' result merely because ASS has no Dialogue rows.
            data = self.get_raw_data(path.stem)
            return (all(header in text for header in ("[Script Info]", "[V4+ Styles]", "[Events]"))
                    and isinstance(data, dict) and data.get("segments") == [])'''),
    ],
    'app/control/app_controller.py': [
        ('        if sub:\n            sub.clear()', '        if sub:\n            sub.load_subtitles([])\n            sub.clear()'),
        ('            self._load_subtitle_to_ui(media_id)\n            self._show_status("📄 Phụ đề có sẵn")',
         '''            if self._load_subtitle_to_ui(media_id) is False:
                self._show_status("ℹ️ Chưa nhận diện được lời (có thể là nhạc không lời).")
            else:
                self._show_status("📄 Phụ đề có sẵn")'''),
        ('        self.subtitle_mgr.save_segments(', '        saved_path = self.subtitle_mgr.save_segments('),
        ('            source_path=source_path \n        )', '''            source_path=source_path 
        )
        if not saved_path:
            self._show_status("❌ Không lưu được phụ đề. Vui lòng kiểm tra thư mục lưu.")
            return'''),
        ('        self._show_status("✨ Phụ đề AI sẵn sàng")', '''        if segments:
            self._show_status("✨ Phụ đề AI sẵn sàng")
        else:
            self._show_status("ℹ️ Đã lưu kết quả rỗng: chưa nhận diện được lời.")'''),
        ('        if not sub or not segments:\n            logger.warning("⚠️ Không có sub_layer hoặc subtitle rỗng")',
         '        if not sub:\n            logger.warning("⚠️ Không có sub_layer")'),
        ('        sub.load_subtitles(segments)\n        sub.show()', '''        sub.load_subtitles(segments)
        if not segments:
            sub.clear()
            sub._smart_hide(instant=True)
            return False
        sub.show()'''),
        ('        sub.center_at_bottom()', '        sub.center_at_bottom()\n        return True'),
    ],
    'app/ui/subs_ui/subtitle_dialog_logic.py': [
        ("        if not self.raw_data or 'segments' not in self.raw_data or not self.raw_data['segments']:",
         "        if not self.raw_data or not isinstance(self.raw_data.get('segments'), list):"),
    ],
}


def before_empty_changes(relative):
    """Check exact patch against snapshot before allowing legacy normalization."""
    snapshot = ROOT / 'docs/empty-subtitles/original' / Path(relative).name
    previous = snapshot.read_text(encoding='utf-8-sig')
    expected = previous
    for old, new in EDITS[relative]:
        if expected.count(old) != 1:
            raise AssertionError(f'Expected one original edit anchor: {relative}: {old!r}')
        expected = expected.replace(old, new, 1)
    from tests.reliability_contracts import before_reliability_changes
    current = before_reliability_changes(relative)
    if ast.dump(ast.parse(current)) != ast.dump(ast.parse(expected)):
        raise AssertionError(f'Unreviewed source change outside empty-result patch: {relative}')
    return previous
