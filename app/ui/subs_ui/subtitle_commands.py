from PySide6.QtGui import QUndoCommand
class ModelSnapshotCommand(QUndoCommand):
    def __init__(self, model, before, after, text="change"):
        super().__init__(text)
        self.model = model
        self.before = before
        self.after = after

    def undo(self):
        self.model.set_segments(self.before)

    def redo(self):
        self.model.set_segments(self.after)


class InsertRowsCommand(ModelSnapshotCommand):
    def __init__(self, model, before, after, text="Insert Row"):
        super().__init__(model, before, after, text)


class RemoveRowsCommand(ModelSnapshotCommand):
    def __init__(self, model, before, after, text="Remove Row"):
        super().__init__(model, before, after, text)


class ReplaceSegmentsCommand(ModelSnapshotCommand):
    def __init__(self, model, before, after, text="Replace Segments"):
        super().__init__(model, before, after, text)


class BatchShiftCommand(ModelSnapshotCommand):
    def __init__(self, model, before, after, delta, text=None):
        txt = text or f"Shift {delta}s"
        super().__init__(model, before, after, txt)


class SplitRowCommand(ModelSnapshotCommand):
    def __init__(self, model, before, after, text="Split Row"):
        super().__init__(model, before, after, text)


class MergeRowsCommand(ModelSnapshotCommand):
    def __init__(self, model, before, after, text="Merge Rows"):
        super().__init__(model, before, after, text)
