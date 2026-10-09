"""Measure only cache persistence: python -m tools.benchmark_library."""

import argparse
import hashlib
import json
import logging
from pathlib import Path
import platform
import statistics
import tempfile
import time
from unittest.mock import patch

from app.core.media_library import MediaLibrary
from app.media.models import MediaMetadata
from app.thumbnail.persistence import ThumbnailPersistenceBatch


def measure(root, mode, count, updates):
    library = MediaLibrary(root / f"{mode}.json")
    library.items = {str(i): MediaMetadata(str(i), f"{i}.mp4", f"Song {i}", duration=180) for i in range(count)}
    batch = ThumbnailPersistenceBatch(library)
    with patch.object(library, "save", wraps=library.save) as save:
        started = time.perf_counter()
        for i in range(updates):
            if mode == "immediate":
                library.update_thumbnail_in_db(str(i), f"{i}.jpg")
            else:
                batch.record(str(i), f"{i}.jpg")
        if mode == "batch":
            batch.flush()
        elapsed = time.perf_counter() - started
        writes = save.call_count
    data = json.loads(library.db_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return {"seconds": elapsed, "writes": writes, "data_sha256": digest}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", type=int, default=1000)
    parser.add_argument("--updates", type=int, default=120)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not (args.items >= args.updates > 0 and args.repeat > 0):
        parser.error("Require items >= updates > 0 and repeat > 0")
    logging.disable(logging.INFO)
    samples = {"immediate": [], "batch": []}
    with tempfile.TemporaryDirectory() as directory:
        for _ in range(args.repeat):
            for mode in samples:
                samples[mode].append(measure(Path(directory), mode, args.items, args.updates))
    digests = {sample["data_sha256"] for runs in samples.values() for sample in runs}
    if len(digests) != 1:
        raise RuntimeError("Persistence modes produced different data")
    result = {
        "python": platform.python_version(), "platform": platform.platform(),
        "items": args.items, "updates": args.updates, "repeat": args.repeat,
        "batch_size": 12, "same_final_data": True,
        "scope": "Temporary synthetic metadata; identical atomic writer in both modes; excludes ffprobe/FFmpeg/UI/GPU/network.",
        "median_seconds": {mode: statistics.median(s["seconds"] for s in runs) for mode, runs in samples.items()},
        "samples": samples,
    }
    output = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
