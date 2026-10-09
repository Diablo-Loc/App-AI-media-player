"""Atomic writes and recoverable publication of owned subtitle artifacts.

Only explicit saves create transactions. Existing subtitle formats stay unchanged.
"""
import json
import os
from pathlib import Path
import tempfile
import threading
import uuid

_locks = {}
_locks_guard = threading.Lock()


def _lock(root):
    with _locks_guard:
        return _locks.setdefault(str(Path(root).resolve()), threading.RLock())


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _target(root, relative):
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()) or target == root.resolve():
        raise ValueError("Subtitle transaction target outside owned store")
    return target


def _remove(directory, root):
    # Flat transaction files only; never recursively delete a computed path.
    if directory.resolve().parent != (root / '.save-transactions').resolve() or directory.is_symlink():
        raise ValueError("Invalid owned transaction directory")
    for file in directory.iterdir():
        if file.is_file() and not file.is_symlink():
            file.unlink()
        else:
            raise ValueError("Unexpected transaction entry")
    directory.rmdir()


def _restore(root, directory, manifest):
    if manifest['state'] != 'committed':
        for i, entry in enumerate(manifest['entries']):
            target = _target(root, entry['target'])
            if entry['existed']:
                atomic_bytes(target, (directory / f'{i}.old').read_bytes())
            else:
                target.unlink(missing_ok=True)
    _remove(directory, root)


def recover(root):
    root = Path(root)
    with _lock(root):
        directory = root / '.save-transactions'
        if not directory.exists():
            return False
        changed = False
        for transaction in directory.iterdir():
            if not transaction.is_dir() or transaction.is_symlink():
                raise ValueError("Invalid transaction entry")
            journal = transaction / 'manifest.json'
            if journal.exists():
                manifest = json.loads(journal.read_text(encoding='utf-8'))
                _restore(root, transaction, manifest)
                changed = True
            else:
                # Preparation did not publish any target before creating a journal.
                _remove(transaction, root)
        return changed


def publish(root, payloads):
    root = Path(root).resolve()
    with _lock(root):
        recover(root)
        directory = root / '.save-transactions' / uuid.uuid4().hex
        directory.mkdir(parents=True)
        entries = []
        journal = directory / 'manifest.json'
        manifest = {'state': 'prepared', 'entries': entries}
        try:
            for i, (path, data) in enumerate(payloads.items()):
                path = _target(root, Path(path).resolve().relative_to(root))
                path.parent.mkdir(parents=True, exist_ok=True)
                entry = {'target': path.relative_to(root).as_posix(), 'existed': path.exists()}
                if entry['existed']:
                    atomic_bytes(directory / f'{i}.old', path.read_bytes())
                atomic_bytes(directory / f'{i}.new', data)
                entries.append(entry)
            atomic_bytes(journal, json.dumps(manifest).encode('utf-8'))
            for i, entry in enumerate(entries):
                os.replace(directory / f'{i}.new', _target(root, entry['target']))
            manifest['state'] = 'committed'
            atomic_bytes(journal, json.dumps(manifest).encode('utf-8'))
        except Exception:
            if journal.exists():
                # Durable journal remains available if rollback itself fails.
                durable = json.loads(journal.read_text(encoding='utf-8'))
                _restore(root, directory, durable)
            else:
                _remove(directory, root)
            raise
        # Committed cleanup failure must not turn a successful save into failure.
        try:
            _remove(directory, root)
        except OSError:
            pass
