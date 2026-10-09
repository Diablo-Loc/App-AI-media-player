# Subtitle editor inline-edit visibility fix

Date: 2026-10-05.

The multi-language subtitle table keeps its existing model, row height, save/undo path, timing, seek behavior and subtitle data. The fix only replaces Qt's implicit cell editor with a small `QLineEdit` delegate whose text, background, border and selection colors are explicit for the app's dark theme.

The editor uses the model's existing font and `Qt.EditRole`, keeps time columns centered, selects the current cell text on entry, and stays inset by one pixel inside the existing 36 px row. Committing still calls the existing `SubtitleTableModel.setData`, so text/timing persistence and undo observation remain on the old path.

Historical source manifests remain frozen. `tests.subtitle_editor_visibility_contracts` validates the reviewed source and restores the pre-fix dialog before the older video-export gate.

Focused regression coverage checks Unicode text loading/selection, explicit readable palette, compact-row geometry, time alignment and the existing model commit path. The project Python 3.11 executable is currently broken on this machine, so these Qt tests could not be executed in this pass; `git diff --check` is still required and native visual confirmation remains separate.
