"""Compare real JPEG decoders against a smooth full-source reference, offline."""
import argparse
import json
from pathlib import Path
import tempfile

from tools.ui_preview import APPLICATION
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from app.ui.media_card import ImageLoader
from app.ui.playlist_thumbnail import PlaylistThumbnailLoader


def source_fixture(path):
    image = QImage(1120, 624, QImage.Format_RGB32)
    painter = QPainter(image)
    painter.fillRect(image.rect(), QColor("#243549"))
    for x in range(0, 1120, 7):
        painter.fillRect(x, 0, 3, 624, QColor(50 + x % 150, 100, 170))
    for y in range(0, 624, 11):
        painter.fillRect(0, y, 1120, 2, QColor("#AD9066"))
    painter.setPen(QColor("#FFFFFF"))
    painter.setFont(QFont("Segoe UI", 60, QFont.Bold))
    painter.drawText(64, 260, "BoTube / Music")
    painter.drawText(64, 380, "Album 2026")
    painter.end()
    image.save(str(path), "JPEG", 92)


def decode(loader):
    results = []
    loader.signals.finished.connect(lambda key, image: results.append(image))
    loader.run()
    if len(results) != 1:
        raise AssertionError("Expected one decoded fixture")
    image = results[0]
    return image.toImage() if hasattr(image, "toImage") else image


def reference_error(image, reference):
    total = 0
    count = 0
    for y in range(8, reference.height() - 8):
        for x in range(8, reference.width() - 8):
            a, b = image.pixelColor(x, y), reference.pixelColor(x, y)
            total += abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue())
            count += 3
    return total / count


def compare(path, width=140, height=78, dpr=1):
    old = decode(ImageLoader("fixture", str(path), width, height))
    new = decode(PlaylistThumbnailLoader("fixture", str(path), width, height, dpr))
    reference = QImage(str(path)).scaled(QSize(width, height), Qt.KeepAspectRatioByExpanding,
                                       Qt.SmoothTransformation)
    return old, new, reference, {
        "source": [1120, 624], "target": [width, height],
        "original_mean_absolute_rgb_error": reference_error(old, reference),
        "new_mean_absolute_rgb_error": reference_error(new, reference),
        "reference": "full JPEG decode then Qt SmoothTransformation; inner pixels",
    }


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="botube-cover-") as directory:
        path = Path(directory) / "fixture.jpg"
        source_fixture(path)
        old, new, reference, report = compare(path)
        for name, image in (("before", old), ("after", new), ("reference", reference)):
            image.save(str(output / f"{name}.png"))
            image.scaled(image.width() * 4, image.height() * 4, Qt.IgnoreAspectRatio,
                         Qt.FastTransformation).save(str(output / f"{name}-4x.png"))
        report["limits"] = "One synthetic JPEG, not a real-media perceptual score or speed benchmark."
        (output / "probe.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
