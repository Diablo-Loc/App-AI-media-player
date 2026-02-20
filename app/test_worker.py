from PySide6.QtWidgets import QApplication
import sys

from worker import AIWorker


def main():
    app = QApplication(sys.argv)

    def on_done(mid, ass):
        print("✅ DONE:", ass)
        app.quit()

    def on_err(mid, err):
        print("❌ ERROR:", err)
        app.quit()

    worker = AIWorker(
        media_id="test_001",
        input_path="input/【歌ってみた】Tell Your World – kz - covered by 月見ヤチヨ(cv.早見沙織) from 超かぐや姫！.mp4"
    )

    worker.finished.connect(on_done)
    worker.failed.connect(on_err)

    worker.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
