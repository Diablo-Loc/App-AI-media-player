import os
import re
import json
from PySide6.QtWidgets import (
    QMessageBox, QApplication, QInputDialog, QFileDialog, QMenu,QAbstractItemView
)
from PySide6.QtCore import Qt, QSettings, QPoint
from PySide6.QtGui import QAction
from ui.subs_ui.subtitle_utils import _parse_time_str, _format_time, _get_app_root
from ui.subs_ui.subtitle_io import load_subs, save_subs
from ui.subs_ui.subtitle_model import SnapshotCommand
from ui.subs_ui.subtitle_commands import (
    InsertRowsCommand, RemoveRowsCommand, ReplaceSegmentsCommand,
    BatchShiftCommand, SplitRowCommand, MergeRowsCommand
)
from ui.subs_ui.subtitle_workers import AlignWorker, TranslationWorker


class SubtitleToolsDialogLogic:
    def _resolve_subtitle_path(self) -> str:
        if not self.media_path and not self.media_id:
            return ""

        filename = os.path.splitext(os.path.basename(self.media_path))[0] if self.media_path else self.media_id
        media_dir = os.path.dirname(self.media_path) if self.media_path else ""
        app_root = _get_app_root()
        storage_dir = os.path.join(app_root, "storage")
        sub_storage_dir = os.path.join(storage_dir, "subtitles")
        os.makedirs(sub_storage_dir, exist_ok=True)

        candidates = [
            os.path.join(sub_storage_dir, f"{self.media_id}.json") if self.media_id else "",
            os.path.join(sub_storage_dir, f"{self.media_id}.ass") if self.media_id else "",
            os.path.join(sub_storage_dir, "source", "srt", f"{filename}.srt"),
            os.path.join(media_dir, "subtitles", f"{filename}.ass") if media_dir else "",
            (os.path.splitext(self.media_path)[0] + ".ass") if self.media_path else ""
        ]

        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                return candidate
        return os.path.join(sub_storage_dir, f"{self.media_id or filename}.json")

    def sync_context_from_parent(self):
        parent = self.parent()
        if parent:
            if hasattr(parent, 'current_media_id') and parent.current_media_id:
                self.media_id = parent.current_media_id
            if hasattr(parent, 'current_media_path') and parent.current_media_path:
                self.media_path = parent.current_media_path
            if hasattr(parent, 'app_controller'):
                ctrl = parent.app_controller
                ctrl_lang = getattr(ctrl, 'detected_lang', '')
                if ctrl_lang:
                    self.detected_lang = ctrl_lang
                if not self.media_id and getattr(ctrl, 'current_media_item', None):
                    self.media_id = getattr(ctrl.current_media_item, 'id', '')
                    self.media_path = getattr(ctrl.current_media_item, 'path', '')

        self.sub_path = self._resolve_subtitle_path()
        idx = self.combo_lang.findText(self.detected_lang.upper())
        if idx >= 0:
            self.combo_lang.setCurrentIndex(idx)

    def _disconnect_player_signals(self):
        if getattr(self, '_connected_player', None):
            try:
                self._connected_player.positionChanged.disconnect(self._on_player_position_changed)
            except Exception:
                pass
            try:
                self._connected_player.playbackStateChanged.disconnect(self._on_playback_state_changed)
            except Exception:
                pass
            self._connected_player = None

    def _on_tab_changed(self, index: int):
        if index != 1:
            self._disconnect_player_signals()
            try:
                if self.playback_timer.isActive():
                    self.playback_timer.stop()
            except Exception:
                pass
            return

        parent = self.parent()
        if not parent or not hasattr(parent, 'app_controller'):
            try:
                if not self.playback_timer.isActive():
                    self.playback_timer.start()
                self._sync_active_sub_highlight()
            except Exception:
                pass
            return

        ctrl = parent.app_controller
        player = getattr(ctrl, 'player', None)
        if player is not None:
            if hasattr(player, 'positionChanged'):
                try:
                    player.positionChanged.connect(self._on_player_position_changed)
                    self._connected_player = player
                except Exception:
                    self._connected_player = None
            if hasattr(player, 'playbackStateChanged'):
                try:
                    player.playbackStateChanged.connect(self._on_playback_state_changed)
                except Exception:
                    pass

        try:
            if not self.playback_timer.isActive():
                self.playback_timer.start()
            self._sync_active_sub_highlight()
        except Exception:
            pass

    def closeEvent(self, event):
        self._cancel_editor_workers()
        try:
            self._disconnect_player_signals()
        except Exception:
            pass
        # Disconnect undo/redo signals if present to avoid callbacks after destruction
        try:
            us = getattr(self, 'undo_stack', None)
            if us is not None:
                try:
                    us.canUndoChanged.disconnect()
                except Exception:
                    pass
                try:
                    us.canRedoChanged.disconnect()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if self.playback_timer.isActive():
                self.playback_timer.stop()
        except Exception:
            pass
        return super().closeEvent(event)

    def _own_editor_worker(self, worker):
        from control.worker_lifecycle import editor_worker_owner
        self._workers_closed = False
        if not getattr(self, '_worker_close_connected', False):
            self.finished.connect(self._cancel_editor_workers)
            self._worker_close_connected = True
        editor_worker_owner().own(worker)

    def _cancel_editor_workers(self):
        self._workers_closed = True
        for name in ('trans_worker', 'align_worker'):
            worker = getattr(self, name, None)
            if worker is not None:
                try:
                    if worker.isRunning():
                        worker.requestInterruption()
                except RuntimeError:
                    pass

    def _on_playback_state_changed(self, state):
        if self.tabs.currentIndex() != 1:
            return
        try:
            self._sync_active_sub_highlight()
        except Exception:
            pass

    def load_from_media_file(self, media_id: str) -> bool:
        parent = self.parent()
        subtitle_mgr = None
        if parent and hasattr(parent, 'app_controller'):
            subtitle_mgr = getattr(parent.app_controller, 'subtitle_mgr', None)

        if subtitle_mgr and media_id:
            self.raw_data = subtitle_mgr.get_raw_data(media_id)

        if not self.raw_data and self.sub_path and self.sub_path.endswith('.json') and os.path.exists(self.sub_path):
            try:
                with open(self.sub_path, 'r', encoding='utf-8') as f:
                    self.raw_data = json.load(f)
            except Exception:
                pass

        if not self.raw_data or not isinstance(self.raw_data.get('segments'), list):
            return False

        if 'language' in self.raw_data and self.raw_data['language']:
            self.detected_lang = self.raw_data['language']
            idx = self.combo_lang.findText(self.detected_lang.upper())
            if idx >= 0:
                self.combo_lang.setCurrentIndex(idx)

        segments = self.raw_data.get('segments', [])
        lines_orig = []
        for seg in segments:
            start = seg.get('start', 0.0)
            end = seg.get('end', 0.0)
            orig_text = seg.get('text', '') or seg.get('orig', '') or seg.get('jp', '')
            lines_orig.append(f"[{start:.2f} --> {end:.2f}] {orig_text}")

        self.editor_orig.setPlainText("\n".join(lines_orig))
        self._update_combined_table_ui(segments)
        self.lbl_info.setText(f"<b>📂 Bài hiện tại:</b> {media_id or 'Đã nạp'}")
        return True

    def on_reload_clicked(self):
        self.sync_context_from_parent()
        if not self.load_from_media_file(self.media_id):
            self.load_subtitle_content()

    def _update_combined_table_ui(self, segments: list):
        self.table_model.set_segments(segments or [])
        self.table_model.set_active_row(-1)
        # keep a cached snapshot representing current known state
        try:
            self._last_snapshot = self.table_model.snapshot()
        except Exception:
            self._last_snapshot = []

        try:
            self.table_combined.resizeColumnsToContents()
        except Exception:
            pass

    def _on_model_data_changed(self, topLeft, bottomRight, roles=None):
        # Called after model data changes (cell edits). Create a snapshot undo
        try:
            after = self.table_model.snapshot()
        except Exception:
            return

        # If the latest command already recorded this 'after' state, skip
        try:
            cnt = self.undo_stack.count()
            if cnt > 0:
                top_cmd = self.undo_stack.command(cnt - 1)
                if hasattr(top_cmd, 'after') and top_cmd.after == after:
                    self._last_snapshot = after
                    return
        except Exception:
            pass

        before = getattr(self, '_last_snapshot', []) or []
        if before == after:
            return

        try:
            cmd = SnapshotCommand(self.table_model, before, after, "Edit Cell")
            self.undo_stack.push(cmd)
        except Exception:
            self._push_undo(before, after, "Edit Cell")

        self._last_snapshot = after

    def _sync_active_sub_highlight(self):
        if self.tabs.currentIndex() != 1:
            return

        parent = self.parent()
        if not parent or not hasattr(parent, 'app_controller'):
            return

        ctrl = parent.app_controller
        curr_time = None
        if hasattr(ctrl, 'get_current_position_seconds') and callable(getattr(ctrl, 'get_current_position_seconds')):
            try:
                curr_time = ctrl.get_current_position_seconds()
            except Exception:
                curr_time = None
        elif hasattr(ctrl, 'player') and hasattr(ctrl.player, 'position'):
            try:
                curr_time = ctrl.player.position() / 1000.0
            except Exception:
                curr_time = None

        if curr_time is None:
            return

        self._sync_active_sub_for_time(float(curr_time))

    def _sync_active_sub_for_time(self, curr_time: float):
        current_active = -1
        for row in range(self.table_model.rowCount()):
            st_text = self.table_model.data(self.table_model.index(row, 0), Qt.DisplayRole) or ""
            et_text = self.table_model.data(self.table_model.index(row, 1), Qt.DisplayRole) or ""
            try:
                st = _parse_time_str(st_text)
                et = _parse_time_str(et_text)
            except Exception:
                continue

            if st <= curr_time <= et:
                current_active = row
                break

        if current_active >= 0 and current_active != self.active_row_index:
            self.table_model.set_active_row(current_active)
            try:
                idx = self.table_model.index(current_active, 2)
                self.table_combined.scrollTo(idx, QAbstractItemView.PositionAtCenter)
            except Exception:
                pass
            self.active_row_index = current_active

    def _on_player_position_changed(self, pos_ms: int):
        try:
            self._sync_active_sub_for_time(float(pos_ms) / 1000.0)
        except Exception:
            pass

    def _highlight_active_row(self, row: int):
        self.table_model.set_active_row(row)

    def _on_table_data_changed(self, topLeft, bottomRight, roles=None):
        pass

    def _snap_times(self):
        sel = self.table_combined.selectionModel().selectedRows()
        if sel:
            rows = sorted(set(idx.row() for idx in sel))
        else:
            rows = list(range(self.table_model.rowCount()))

        for r in rows:
            st_text = self.table_model.data(self.table_model.index(r, 0), Qt.DisplayRole) or "0"
            et_text = self.table_model.data(self.table_model.index(r, 1), Qt.DisplayRole) or "0"
            try:
                st = _parse_time_str(st_text)
                et = _parse_time_str(et_text)
            except Exception:
                continue

            def snap(x):
                return round(round(x / 0.05) * 0.05, 2)

            new_st = snap(st)
            new_et = snap(et)
            if new_et < new_st:
                new_et = round(new_st + 0.05, 2)

            self.table_model.setData(self.table_model.index(r, 0), _format_time(new_st))
            self.table_model.setData(self.table_model.index(r, 1), _format_time(new_et))

    def _push_undo(self, before: list, after: list, text: str):
        try:
            cmd = SnapshotCommand(self.table_model, before, after, text)
            self.undo_stack.push(cmd)
        except Exception:
            pass

    def _on_row_double_clicked(self, index):
        row = index.row()
        self._seek_to_row(row)

    def _seek_to_row(self, row: int):
        parent = self.parent()
        if not parent or not hasattr(parent, 'app_controller'):
            return
        ctrl = parent.app_controller
        st_text = self.table_model.data(self.table_model.index(row, 0), Qt.DisplayRole) or "0"
        try:
            sec = _parse_time_str(st_text)
        except Exception:
            return

        try:
            if hasattr(ctrl, 'seek') and callable(getattr(ctrl, 'seek')):
                ctrl.seek(sec)
            elif hasattr(ctrl, 'player') and hasattr(ctrl.player, 'setPosition'):
                ctrl.player.setPosition(int(sec * 1000))
        except Exception:
            pass

    def _on_row_clicked(self, index):
        row = index.row()
        mods = QApplication.keyboardModifiers()
        if mods & Qt.ControlModifier:
            self._seek_to_row(row)

    def _hide_and_return(self):
        try:
            if getattr(self, '_connected_player', None):
                try:
                    self._connected_player.positionChanged.disconnect(self._on_player_position_changed)
                except Exception:
                    pass
                self._connected_player = None
        except Exception:
            pass

        try:
            if self.playback_timer.isActive():
                self.playback_timer.stop()
        except Exception:
            pass

        self.hide()

    def _on_table_context_menu(self, point: QPoint):
        idx = self.table_combined.indexAt(point)
        row = idx.row() if idx.isValid() else -1
        menu = QMenu(self)

        act_seek = QAction("Seek to Start", self)
        act_seek.triggered.connect(lambda: self._seek_to_row(row) if row >= 0 else None)
        menu.addAction(act_seek)

        act_split = QAction("Split Row (mid)", self)
        act_split.triggered.connect(lambda: self._action_split(row))
        menu.addAction(act_split)

        act_merge = QAction("Merge with Next", self)
        act_merge.triggered.connect(lambda: self._action_merge(row))
        menu.addAction(act_merge)

        menu.addSeparator()

        act_shift_plus = QAction("Shift +0.5s", self)
        act_shift_plus.triggered.connect(lambda: self._action_shift_selected(0.5))
        menu.addAction(act_shift_plus)

        act_shift_minus = QAction("Shift -0.5s", self)
        act_shift_minus.triggered.connect(lambda: self._action_shift_selected(-0.5))
        menu.addAction(act_shift_minus)

        act_batch = QAction("Batch Shift...", self)
        act_batch.triggered.connect(self._action_batch_shift)
        menu.addAction(act_batch)

        menu.addSeparator()
        act_delete = QAction("Delete Row", self)
        act_delete.triggered.connect(self._delete_table_row)
        menu.addAction(act_delete)

        menu.exec(self.table_combined.viewport().mapToGlobal(point))

    def _action_split(self, row: int):
        if row < 0 or row >= self.table_model.rowCount():
            return
        before = self.table_model.snapshot()
        st = float(self.table_model._segments[row]['start'])
        et = float(self.table_model._segments[row]['end'])
        mid = round((st + et) / 2.0, 2)
        seg = dict(self.table_model._segments[row])
        self.table_model._segments[row]['end'] = mid
        new_seg = dict(seg)
        new_seg['start'] = mid
        new_seg['end'] = et
        self.table_model.insertRows(row + 1, 1)
        self.table_model._segments[row + 1] = new_seg
        self.table_model.dataChanged.emit(self.table_model.index(row, 0), self.table_model.index(row + 1, 4), [Qt.DisplayRole])
        after = self.table_model.snapshot()
        try:
            cmd = SplitRowCommand(self.table_model, before, after, "Split Row")
            self.undo_stack.push(cmd)
        except Exception:
            self._push_undo(before, after, "Split Row")

    def _action_merge(self, row: int):
        if row < 0 or row + 1 >= self.table_model.rowCount():
            return
        before = self.table_model.snapshot()
        first = dict(self.table_model._segments[row])
        second = dict(self.table_model._segments[row + 1])
        merged = {
            'start': first['start'],
            'end': second['end'],
            'text': (first.get('text', '') or '') + ' ' + (second.get('text', '') or ''),
            'orig': (first.get('orig', '') or '') + ' ' + (second.get('orig', '') or ''),
            'en': (first.get('en', '') or '') + ' ' + (second.get('en', '') or ''),
            'vi': (first.get('vi', '') or '') + ' ' + (second.get('vi', '') or '')
        }
        self.table_model._segments[row] = merged
        self.table_model.removeRows(row + 1, 1)
        self.table_model.dataChanged.emit(self.table_model.index(row, 0), self.table_model.index(row, 4), [Qt.DisplayRole])
        after = self.table_model.snapshot()
        try:
            cmd = MergeRowsCommand(self.table_model, before, after, "Merge Rows")
            self.undo_stack.push(cmd)
        except Exception:
            self._push_undo(before, after, "Merge Rows")

    def _action_shift_selected(self, delta_seconds: float):
        sel = self.table_combined.selectionModel().selectedRows()
        if sel:
            rows = sorted(set(idx.row() for idx in sel))
        else:
            rows = list(range(self.table_model.rowCount()))
        before = self.table_model.snapshot()
        for r in rows:
            try:
                self.table_model._segments[r]['start'] = round(float(self.table_model._segments[r]['start']) + delta_seconds, 3)
                self.table_model._segments[r]['end'] = round(float(self.table_model._segments[r]['end']) + delta_seconds, 3)
            except Exception:
                pass
        self.table_model.dataChanged.emit(self.table_model.index(0, 0), self.table_model.index(self.table_model.rowCount()-1, 4), [Qt.DisplayRole])
        after = self.table_model.snapshot()
        try:
            cmd = BatchShiftCommand(self.table_model, before, after, delta_seconds)
            self.undo_stack.push(cmd)
        except Exception:
            self._push_undo(before, after, f"Shift {delta_seconds}s")

    def _action_batch_shift(self):
        ok, val = QInputDialog.getDouble(self, "Batch Shift", "Shift seconds (use negative to move earlier):", 0.5, -3600.0, 3600.0, 2)
        if not ok:
            return
        delta = float(val)
        sel = self.table_combined.selectionModel().selectedRows()
        if sel:
            rows = sorted(set(idx.row() for idx in sel))
        else:
            rows = list(range(self.table_model.rowCount()))
        before = self.table_model.snapshot()
        for r in rows:
            try:
                self.table_model._segments[r]['start'] = round(float(self.table_model._segments[r]['start']) + delta, 3)
                self.table_model._segments[r]['end'] = round(float(self.table_model._segments[r]['end']) + delta, 3)
            except Exception:
                pass
        self.table_model.dataChanged.emit(self.table_model.index(0, 0), self.table_model.index(self.table_model.rowCount()-1, 4), [Qt.DisplayRole])
        after = self.table_model.snapshot()
        try:
            cmd = BatchShiftCommand(self.table_model, before, after, delta)
            self.undo_stack.push(cmd)
        except Exception:
            self._push_undo(before, after, f"Batch Shift {delta}s")

    def _shortcut_split_current(self):
        idx = self.table_combined.currentIndex()
        row = idx.row() if idx.isValid() else -1
        self._action_split(row)

    def _shortcut_merge_current(self):
        idx = self.table_combined.currentIndex()
        row = idx.row() if idx.isValid() else -1
        self._action_merge(row)

    def _shortcut_shift_current(self, delta: float):
        self._action_shift_selected(delta)

    def _reset_row_style(self, row: int):
        self.table_model.set_active_row(-1)

    def _add_table_row(self):
        before = self.table_model.snapshot()
        current_index = self.table_combined.currentIndex()
        current_row = current_index.row() if current_index.isValid() else -1
        insert_row = current_row + 1 if current_row >= 0 else self.table_model.rowCount()

        self.table_model.insertRows(insert_row, 1)

        if insert_row > 0 and self.table_model.rowCount() > 1:
            prev_end_text = self.table_model.data(self.table_model.index(insert_row - 1, 1), Qt.DisplayRole)
            prev_end_str = prev_end_text if prev_end_text else "0.00"
            start_val = _format_time(_parse_time_str(prev_end_str))
        else:
            start_val = "0.00"

        end_val = _format_time(_parse_time_str(start_val) + 3.0)

        self.table_model.setData(self.table_model.index(insert_row, 0), start_val)
        self.table_model.setData(self.table_model.index(insert_row, 1), end_val)
        self.table_model.setData(self.table_model.index(insert_row, 2), "")
        self.table_model.setData(self.table_model.index(insert_row, 3), "")
        self.table_model.setData(self.table_model.index(insert_row, 4), "")

        self.table_combined.selectRow(insert_row)
        self.table_combined.setCurrentIndex(self.table_model.index(insert_row, 2))
        after = self.table_model.snapshot()
        try:
            cmd = InsertRowsCommand(self.table_model, before, after, "Insert Row")
            self.undo_stack.push(cmd)
        except Exception:
            self._push_undo(before, after, "Insert Row")

    def _delete_table_row(self):
        current_index = self.table_combined.currentIndex()
        current_row = current_index.row() if current_index.isValid() else -1
        if current_row >= 0:
            before = self.table_model.snapshot()
            self.table_model.removeRows(current_row, 1)
            after = self.table_model.snapshot()
            try:
                cmd = RemoveRowsCommand(self.table_model, before, after, "Delete Row")
                self.undo_stack.push(cmd)
            except Exception:
                self._push_undo(before, after, "Delete Row")
            next_row = min(current_row, self.table_model.rowCount() - 1)
            if next_row >= 0:
                self.table_combined.selectRow(next_row)
                self.table_combined.setCurrentIndex(self.table_model.index(next_row, 2))

    def _handle_paste_shortcut(self):
        if self.tabs.currentIndex() == 1 and self.table_combined.hasFocus():
            self.paste_to_table()

    def paste_to_table(self):
        text = QApplication.clipboard().text().strip()
        if not text:
            return

        parsed_segments = self._parse_text_to_segments(text)
        if not parsed_segments:
            QMessageBox.warning(self, "Cảnh báo", "Nội dung dán không hợp lệ hoặc không nhận diện được phụ đề!")
            return

        reply = QMessageBox.question(
            self, "Xác nhận dán",
            f"Bạn có muốn THAY THẾ toàn bộ bảng bằng {len(parsed_segments)} dòng phụ đề từ Clipboard không?\n\n(Chọn No để CHÈN Nối Tiếp vào cuối bảng)",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
        )

        if reply == QMessageBox.Cancel:
            return
        elif reply == QMessageBox.Yes:
            before = self.table_model.snapshot()
            self._update_combined_table_ui(parsed_segments)
            after = self.table_model.snapshot()
            try:
                cmd = ReplaceSegmentsCommand(self.table_model, before, after, "Replace Table")
                self.undo_stack.push(cmd)
            except Exception:
                self._push_undo(before, after, "Replace Table")
        else:
            before = self.table_model.snapshot()
            for seg in parsed_segments:
                row = self.table_model.rowCount()
                self.table_model.insertRows(row, 1)
                self.table_model.setData(self.table_model.index(row, 0), _format_time(seg.get('start', 0.0)))
                self.table_model.setData(self.table_model.index(row, 1), _format_time(seg.get('end', 0.0)))
                self.table_model.setData(self.table_model.index(row, 2), seg.get('text', ''))
                self.table_model.setData(self.table_model.index(row, 3), seg.get('en', ''))
                self.table_model.setData(self.table_model.index(row, 4), seg.get('vi', ''))
            after = self.table_model.snapshot()
            try:
                cmd = ReplaceSegmentsCommand(self.table_model, before, after, "Paste Append Segments")
                self.undo_stack.push(cmd)
            except Exception:
                self._push_undo(before, after, "Paste Segments")

    def _import_subs(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Subtitles", "", "Subtitle Files (*.json *.srt *.ass);;All Files (*)")
        if not path:
            return
        try:
            segments = load_subs(path)
        except Exception:
            QMessageBox.warning(self, "Lỗi", "Không thể đọc file phụ đề.")
            return

        if not segments:
            QMessageBox.warning(self, "Lỗi", "File không chứa phụ đề hợp lệ.")
            return

        before = self.table_model.snapshot()
        self.table_model.set_segments(segments)
        after = self.table_model.snapshot()
        self._push_undo(before, after, "Import Subtitles")

    def _export_subs(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Subtitles", "", "Subtitle Files (*.json *.srt *.ass);;All Files (*)")
        if not path:
            return
        try:
            segments = self.table_model.get_segments()
            save_subs(path, segments)
        except Exception:
            QMessageBox.warning(self, "Lỗi", "Không thể lưu file phụ đề.")

    def _parse_text_to_segments(self, text: str) -> list:
        normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
        blocks = re.split(r'\n\s*\n', normalized_text)
        parsed = []
        for i, block in enumerate(blocks):
            lines = [l.strip() for l in block.splitlines() if l.strip()]
            if not lines:
                continue

            start, end = round(i * 3.0, 2), round(i * 3.0 + 2.8, 2)
            orig_text, en, vi = "", "", ""
            time_match = re.search(r'\[\s*([\d:.,]+)\s*-->\s*([\d:.,]+)\s*\]', lines[0])
            start_idx = 0
            if time_match:
                start = _parse_time_str(time_match.group(1))
                end = _parse_time_str(time_match.group(2))
                start_idx = 1

            for line in lines[start_idx:]:
                if ':' in line:
                    parts = line.split(':', 1)
                    tag = parts[0].strip().upper()
                    val = parts[1].strip()
                    if tag == 'EN':
                        en = val
                    elif tag == 'VI':
                        vi = val
                    else:
                        orig_text = val
                else:
                    if not orig_text:
                        orig_text = line
                    elif not en:
                        en = line
                    elif not vi:
                        vi = line

            parsed.append({
                "start": start,
                "end": end,
                "text": orig_text or en or vi,
                "orig": orig_text or en or vi,
                "en": en,
                "vi": vi
            })
        return parsed

    def load_subtitle_content(self):
        if self.sub_path and os.path.exists(self.sub_path):
            try:
                with open(self.sub_path, "r", encoding="utf-8-sig", errors="ignore") as f:
                    content = f.read()
                self.editor_orig.setPlainText(content)
                self.lbl_info.setText(f"<b>📂 File phụ đề:</b> {self.sub_path}")
            except Exception as e:
                QMessageBox.warning(self, "Lỗi đọc file", f"Không thể đọc file: {e}")

    def start_auto_translation(self):
        parsed_orig = self._parse_tab_orig()
        if not parsed_orig:
            QMessageBox.warning(self, "Cảnh báo", "Tab phụ đề gốc không có dữ liệu để dịch!")
            return

        settings = QSettings("MyStudio", "AI_Music_Player")
        api_key = ""
        parent = self.parent()
        if parent and hasattr(parent, 'app_controller'):
            ctrl = parent.app_controller
            api_key = getattr(ctrl, 'api_key', '')
        if not api_key:
            api_key = (
                settings.value("api_key", "").strip()
                or settings.value("gemini_key", "").strip()
                or settings.value("openai_key", "").strip()
                or settings.value("claude_key", "").strip()
            )

        online_provider = settings.value("online_provider", "Local Default")
        if parent and hasattr(parent, 'app_controller'):
            ctrl = parent.app_controller
            online_provider = getattr(ctrl, 'online_provider', online_provider)

        app_settings = {
            "use_online_translation": bool(api_key and online_provider != "Local Default"),
            "online_provider": online_provider,
            "api_key": api_key,
            "detected_lang": self.detected_lang,
            "song_title_raw": getattr(parent.app_controller, 'song_title_raw', '') if (parent and hasattr(parent, 'app_controller')) else '',
            "translate_mode": "default",
        }

        self.btn_translate.setEnabled(False)
        self.btn_translate.setText("⏳ Đang Dịch Thuật...")
        self.progress_bar.show()

        self.trans_worker = TranslationWorker(parsed_orig, app_settings, self)
        self._own_editor_worker(self.trans_worker)
        self.trans_worker.finished_signal.connect(self._on_translation_finished)
        self.trans_worker.error_signal.connect(self._on_translation_error)
        self.trans_worker.start()

    def _on_translation_finished(self, updated_segments):
        if getattr(self, '_workers_closed', False): return
        self.btn_translate.setEnabled(True)
        self.btn_translate.setText("🤖 Tự Động Dịch (AI)")
        self.progress_bar.hide()

        self._update_combined_table_ui(updated_segments)
        self.tabs.setCurrentIndex(1)

        QMessageBox.information(
            self, "Dịch Hoàn Tất",
            "✅ Đã tự động dịch xong!\nKết quả đã được cập nhật lên Bảng Phụ Đề.\n\nHãy nhấn 'Lưu & Cập Nhật' để hoàn tất."
        )

    def _on_translation_error(self, err_msg):
        if getattr(self, '_workers_closed', False): return
        self.btn_translate.setEnabled(True)
        self.btn_translate.setText("🤖 Tự Động Dịch (AI)")
        self.progress_bar.hide()
        QMessageBox.critical(self, "Lỗi Dịch Thuật", f"Không thể hoàn tất dịch thuật:\n{err_msg}")

    def copy_text(self):
        if self.tabs.currentIndex() == 0:
            text = self.editor_orig.toPlainText()
        else:
            lines = []
            lang_tag = self.detected_lang.upper() if self.detected_lang and self.detected_lang != "AUTO" else "JA"
            for r in range(self.table_model.rowCount()):
                st = self.table_model.data(self.table_model.index(r, 0), Qt.DisplayRole) or "0.00"
                et = self.table_model.data(self.table_model.index(r, 1), Qt.DisplayRole) or "0.00"
                orig = self.table_model.data(self.table_model.index(r, 2), Qt.DisplayRole) or ""
                en = self.table_model.data(self.table_model.index(r, 3), Qt.DisplayRole) or ""
                vi = self.table_model.data(self.table_model.index(r, 4), Qt.DisplayRole) or ""
                lines.append(f"[{st} --> {et}]\n{lang_tag}: {orig}\nEN: {en}\nVI: {vi}")
            text = "\n\n".join(lines)

        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "Thông báo", "📋 Đã copy nội dung tab vào Clipboard!")

    def _parse_tab_orig(self) -> list:
        raw_text = self.editor_orig.toPlainText().strip()
        if not raw_text:
            return []

        parsed = []
        for i, line in enumerate(raw_text.splitlines()):
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            match = re.search(r'\[\s*([\d:.,]+)\s*-->\s*([\d:.,]+)\s*\]\s*(.*)', line)
            if match:
                start = _parse_time_str(match.group(1))
                end = _parse_time_str(match.group(2))
                text = match.group(3).strip()
            else:
                start = round(i * 3.0, 2)
                end = round(i * 3.0 + 2.8, 2)
                text = line
            parsed.append({"start": start, "end": end, "text": text, "orig": text})
        return parsed

    def _parse_table_combined(self) -> list:
        try:
            self.table_combined.clearFocus()
        except Exception:
            pass
        parsed = []
        for r in range(self.table_model.rowCount()):
            st_text = self.table_model.data(self.table_model.index(r, 0), Qt.DisplayRole) or ""
            et_text = self.table_model.data(self.table_model.index(r, 1), Qt.DisplayRole) or ""
            orig = self.table_model.data(self.table_model.index(r, 2), Qt.DisplayRole) or ""
            en = self.table_model.data(self.table_model.index(r, 3), Qt.DisplayRole) or ""
            vi = self.table_model.data(self.table_model.index(r, 4), Qt.DisplayRole) or ""
            start = _parse_time_str(st_text) if st_text else 0.0
            end = _parse_time_str(et_text) if et_text else start + 2.8
            if orig or en or vi:
                parsed.append({
                    "start": start,
                    "end": end,
                    "text": orig or en or vi,
                    "orig": orig or en or vi,
                    "en": en,
                    "vi": vi
                })
        return parsed

    def save_subtitle_content(self):
        self.sync_context_from_parent()
        self.sub_path = self._resolve_subtitle_path()
        if hasattr(self, 'table_combined'):
            try:
                self.table_combined.clearSelection()
                self.table_combined.clearFocus()
            except Exception:
                pass
        current_idx = self.tabs.currentIndex()
        if current_idx == 0:
            parsed_data = self._parse_tab_orig()
            if not parsed_data:
                parsed_data = self._parse_table_combined()
        else:
            parsed_data = self._parse_table_combined()
            if not parsed_data:
                parsed_data = self._parse_tab_orig()
        if not parsed_data:
            QMessageBox.warning(self, "Cảnh báo", "Không có dữ liệu phụ đề để lưu!")
            return
        parent = self.parent()
        subtitle_mgr = None
        media_id = self.media_id
        if parent and hasattr(parent, 'app_controller'):
            subtitle_mgr = getattr(parent.app_controller, 'subtitle_mgr', None)
        if media_id and subtitle_mgr:
            raw = subtitle_mgr.get_raw_data(media_id) or {"media_id": media_id, "segments": []}
            existing_segments = raw.get('segments', [])
            new_segments = []
            for idx, item in enumerate(parsed_data):
                existing = existing_segments[idx] if idx < len(existing_segments) else {}
                seg_dict = dict(existing)
                seg_dict["start"] = float(item.get('start', 0.0))
                seg_dict["end"] = float(item.get('end', 0.0))
                new_text = item.get('text') or item.get('orig') or ''
                seg_dict["text"] = new_text
                seg_dict["orig"] = new_text
                if "jp" in seg_dict:
                    seg_dict["jp"] = new_text
                if current_idx == 1 or 'en' in item:
                    seg_dict["en"] = item.get('en', '')
                    seg_dict["vi"] = item.get('vi', '')
                new_segments.append(seg_dict)
            raw['segments'] = new_segments
            raw['language'] = self.detected_lang if self.detected_lang != "auto" else "en"
            try:
                if subtitle_mgr.save_raw_data(media_id, raw) is not True:
                    QMessageBox.warning(self, "Không lưu được", "Không thể lưu phụ đề. Bản đã lưu trước đó được giữ nguyên; hãy thử lại.")
                    return
                if hasattr(subtitle_mgr, 'cache'):
                    subtitle_mgr.cache.pop(media_id, None)
                if hasattr(subtitle_mgr, 'raw_cache'):
                    subtitle_mgr.raw_cache.pop(media_id, None)
                if parent and hasattr(parent, 'app_controller'):
                    ctrl = parent.app_controller
                    if hasattr(ctrl, '_load_subtitle_to_ui'):
                        if hasattr(ctrl, 'current_subtitle_id'):
                            ctrl.current_subtitle_id = None
                        ctrl._load_subtitle_to_ui(media_id)
                    if hasattr(ctrl, 'sub_layer') and ctrl.sub_layer:
                        ctrl.sub_layer.update()
                QMessageBox.information(self, "Thành công", f"✅ Đã lưu và cập nhật {len(new_segments)} câu phụ đề thành công!")
                self.accept()
                return
            except Exception as e:
                QMessageBox.warning(self, "Không lưu được", f"Không thể lưu phụ đề: {e}")
                return
        if self.sub_path:
            try:
                os.makedirs(os.path.dirname(os.path.abspath(self.sub_path)), exist_ok=True)
                if self.sub_path.endswith('.json'):
                    json_data = {"media_id": media_id or "default", "language": self.detected_lang, "segments": parsed_data}
                    from core.subtitle_persistence import atomic_bytes
                    atomic_bytes(self.sub_path, json.dumps(json_data, ensure_ascii=False, indent=2).encode('utf-8'))
                else:
                    from core.subtitle_persistence import atomic_bytes
                    atomic_bytes(self.sub_path, self.editor_orig.toPlainText().encode('utf-8'))
                QMessageBox.information(self, "Thành công", "✅ Đã ghi file phụ đề thành công!")
                self.accept()
            except Exception as e:
                QMessageBox.critical(self, "Lỗi ghi file", f"Không thể lưu file: {e}")

    def show_above_widget(self, target_widget=None):
        self.sync_context_from_parent()
        self.on_reload_clicked()
        top_window = target_widget.window() if target_widget else None
        if top_window:
            geo = top_window.geometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 2
        else:
            screen = QApplication.primaryScreen().geometry()
            x = (screen.width() - self.width()) // 2
            y = (screen.height() - self.height()) // 2
        self.move(x, y)
        self.exec()

    def align_whisper_with_reference(self):
        whisper_lines = self._parse_tab_orig()
        if not whisper_lines:
            QMessageBox.warning(self, "Cảnh báo", "Tab Phụ Đề Gốc đang rỗng!")
            return

        default_ref = getattr(self, "reference_lyric", "") or ""
        ref_text, ok = QInputDialog.getMultiLineText(
            self,
            "✨ Khớp & Sửa Lời Chuẩn",
            "Dán Lời Bài Hát Chuẩn vào đây:",
            default_ref
        )
        if not ok or not ref_text.strip():
            return

        settings = QSettings("MyStudio", "AI_Music_Player")
        provider = settings.value("online_provider", "Local Default")
        if provider == "Local Default":
            QMessageBox.warning(
                self,
                "Cảnh báo",
                "Vui lòng chọn một dịch vụ AI Online trong Cài đặt trước khi Khớp Lời."
            )
            return
        api_key = (
            settings.value("api_key", "").strip()
            or settings.value("gemini_key", "").strip()
            or settings.value("openai_key", "").strip()
            or settings.value("claude_key", "").strip()
        )
        if not api_key:
            QMessageBox.warning(
                self,
                "Cảnh báo",
                "Vui lòng cài đặt API Key trong Cài đặt ứng dụng!"
            )
            return

        self.btn_align.setEnabled(False)
        self.btn_align.setText("⏳ Đang Khớp Lời...")
        self.progress_bar.show()

        self.align_worker = AlignWorker(whisper_lines, ref_text, provider, api_key, self)
        self._own_editor_worker(self.align_worker)
        self.align_worker.finished_signal.connect(self._on_align_finished)
        self.align_worker.error_signal.connect(self._on_align_error)
        self.align_worker.start()

    def _on_align_finished(self, lines_output, count_updated):
        if getattr(self, '_workers_closed', False): return
        self.btn_align.setEnabled(True)
        self.btn_align.setText("✨ Khớp & Sửa Lời Chuẩn (Align Lyrics)")
        self.progress_bar.hide()
        self.editor_orig.setPlainText("\n".join(lines_output))
        QMessageBox.information(
            self,
            "✅ Hoàn tất",
            f"Đã sửa {count_updated}/{len(lines_output)} dòng theo Lời Chuẩn!"
        )

    def _on_align_error(self, err_msg):
        if getattr(self, '_workers_closed', False): return
        self.btn_align.setEnabled(True)
        self.btn_align.setText("✨ Khớp & Sửa Lời Chuẩn (Align Lyrics)")
        self.progress_bar.hide()
        QMessageBox.critical(
            self,
            "❌ Lỗi Align Lyrics",
            f"Không thể xử lý:\n{err_msg}"
        )
