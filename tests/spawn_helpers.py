"""Small importable child targets for process integration checks (no AI models)."""


def return_subtitle(input_path, output_dir, media_id, queue, cancel_event):
    from app.subtitle.model import Subtitle, SubtitleLine

    queue.put(("finished", {"segments": [Subtitle(0, 1, SubtitleLine("hello", "en", "EN"))]}))
