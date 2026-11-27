"""Centralized, thread-safe, atomic persistence for personal user collections:
- Watch History (grouped by date, bounded by max_days & max_items)
- Favorites (O(1) lookup + ordered list)
- Personal Playlists (CRUD + track ordering)
- Multi-Folder Media Sources (with legacy ConfigManager.last_folder compatibility)
- Smart Resume / Last-Played Session State (coalesced position updates, zero I/O spam)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QObject, QTimer, Signal

from core.media_library import MediaMetadata
from core.subtitle_persistence import atomic_bytes
import paths as _paths

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_HISTORY_MAX_DAYS = 30
DEFAULT_HISTORY_MAX_ITEMS = 300
MAX_PLAY_STATS_ENTRIES = 500
MAX_DAILY_PLAY_DAYS = 95
ALLOWED_HISTORY_DAYS = (7, 14, 30, 90, 0)
ALLOWED_HISTORY_ITEMS = (50, 100, 200, 300, 500)

_VI_WEEKDAYS = (
    "Thứ Hai",
    "Thứ Ba",
    "Thứ Tư",
    "Thứ Năm",
    "Thứ Sáu",
    "Thứ Bảy",
    "Chủ Nhật",
)


def _norm_folder_key(folder_path: str) -> str:
    try:
        resolved = str(Path(folder_path).resolve())
    except OSError:
        resolved = os.path.normpath(str(folder_path))
    return os.path.normcase(resolved)


def _clean_folder_display(folder_path: str) -> str:
    if not folder_path or not str(folder_path).strip():
        return ""
    raw = str(folder_path).strip()
    try:
        return str(Path(raw).resolve())
    except OSError:
        return os.path.normpath(raw)


def snapshot_media_item(item: Any) -> Optional[Dict[str, Any]]:
    """Serialize MediaMetadata or dict-like media object into a resilient JSON dict."""
    if item is None:
        return None
    if isinstance(item, dict):
        media_id = str(item.get("id") or "").strip()
        path = str(item.get("path") or "").strip()
        if not media_id and not path:
            return None
        title = str(item.get("title") or (Path(path).stem if path else "Unknown"))
        artist = str(item.get("artist") or "Unknown Artist")
        try:
            duration = max(0.0, float(item.get("duration") or 0.0))
        except (TypeError, ValueError):
            duration = 0.0
        thumb = item.get("thumbnail") or None
        mtime = item.get("mtime")
        try:
            mtime_val = float(mtime) if mtime is not None else None
        except (TypeError, ValueError):
            mtime_val = None
        return {
            "id": media_id or path,
            "path": path,
            "title": title,
            "artist": artist,
            "duration": duration,
            "thumbnail": str(thumb) if thumb else None,
            "mtime": mtime_val,
        }

    media_id = str(getattr(item, "id", "") or "").strip()
    path = str(getattr(item, "path", "") or "").strip()
    if not media_id and not path:
        return None
    title = str(getattr(item, "title", "") or (Path(path).stem if path else "Unknown"))
    artist = str(getattr(item, "artist", "") or "Unknown Artist")
    try:
        duration = max(0.0, float(getattr(item, "duration", 0.0) or 0.0))
    except (TypeError, ValueError):
        duration = 0.0
    thumb = getattr(item, "thumbnail", None)
    mtime = getattr(item, "mtime", None)
    try:
        mtime_val = float(mtime) if mtime is not None else None
    except (TypeError, ValueError):
        mtime_val = None
    return {
        "id": media_id or path,
        "path": path,
        "title": title,
        "artist": artist,
        "duration": duration,
        "thumbnail": str(thumb) if thumb else None,
        "mtime": mtime_val,
    }


def resolve_media_item(entry: Dict[str, Any], media_library: Any = None) -> MediaMetadata:
    """Return live MediaMetadata from MediaLibrary if loaded, else reconstruct from snapshot."""
    media_id = str(entry.get("id") or "")
    if media_library is not None and hasattr(media_library, "items"):
        lock = getattr(media_library, "lock", None)
        if lock is not None:
            with lock:
                live = media_library.items.get(media_id)
        else:
            live = media_library.items.get(media_id)
        if live is not None:
            return live

    path = str(entry.get("path") or "")
    title = str(entry.get("title") or (Path(path).stem if path else "Unknown"))
    artist = str(entry.get("artist") or "Unknown Artist")
    try:
        duration = max(0.0, float(entry.get("duration") or 0.0))
    except (TypeError, ValueError):
        duration = 0.0
    thumb = entry.get("thumbnail") or None
    mtime = entry.get("mtime")
    try:
        mtime_val = float(mtime) if mtime is not None else None
    except (TypeError, ValueError):
        mtime_val = None
    return MediaMetadata(
        id=media_id,
        path=path,
        title=title,
        artist=artist,
        thumbnail=str(thumb) if thumb else None,
        duration=duration,
        mtime=mtime_val,
    )


def format_date_section_label(date_key: str, today: Optional[date] = None) -> str:
    """Format 'YYYY-MM-DD' into 'Hôm nay — DD/MM/YYYY', 'Hôm qua — DD/MM/YYYY', or 'Thứ ..., DD/MM/YYYY'."""
    ref_today = today or datetime.now().date()
    try:
        parsed = datetime.strptime(date_key, "%Y-%m-%d").date()
    except ValueError:
        return date_key
    ddmmyyyy = parsed.strftime("%d/%m/%Y")
    delta_days = (ref_today - parsed).days
    if delta_days == 0:
        return f"Hôm nay — {ddmmyyyy}"
    if delta_days == 1:
        return f"Hôm qua — {ddmmyyyy}"
    weekday_vi = _VI_WEEKDAYS[parsed.weekday()]
    return f"{weekday_vi}, {ddmmyyyy}"


def format_duration_mmss(seconds: float) -> str:
    total = max(0, int(round(float(seconds or 0.0))))
    hrs, rem = divmod(total, 3600)
    mins, secs = divmod(rem, 60)
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def format_listen_duration_vi(seconds: float) -> str:
    """Human-readable Vietnamese listening duration (e.g., '2 giờ 15 phút', '18 phút', '45 giây')."""
    total = max(0, int(round(float(seconds or 0.0))))
    if total < 60:
        return f"{total} giây"
    hrs, rem = divmod(total, 3600)
    mins = rem // 60
    if hrs > 0:
        return f"{hrs} giờ {mins} phút" if mins > 0 else f"{hrs} giờ"
    return f"{mins} phút"


def compute_play_count_threshold_sec(duration_sec: float) -> float:
    """Return required real continuous listening seconds to qualify as 1 play:
    - Standard tracks (<= 8 min): > 50% of track duration
    - Long videos/mixes (> 8 min): 240s (4 minutes, industry scrobble cap)
    - Unknown duration (<= 0): 30s fallback
    """
    dur = float(duration_sec or 0.0)
    if dur <= 0.0:
        return 30.0
    return min(dur * 0.5, 240.0)


@dataclass(frozen=True)
class HistoryItemView:
    media: MediaMetadata
    watched_at: float
    date_key: str
    time_text: str
    watch_count: int


@dataclass(frozen=True)
class TopTrackView:
    rank: int
    media: MediaMetadata
    play_count: int
    total_listen_sec: float
    last_played_at: float
    share_ratio: float


class UserCollectionsStore(QObject):
    """Owned store for History, Favorites, Personal Playlists, Top Most Played, Multi-Folders, and Last-Played state."""

    favorites_changed = Signal()
    playlists_changed = Signal()
    history_changed = Signal()
    stats_changed = Signal()
    folders_changed = Signal()
    last_played_changed = Signal()

    def __init__(self, store_path: Optional[str | Path] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.store_path = Path(store_path) if store_path is not None else (_paths.storage_dir() / "user_collections.json")
        self._lock = threading.RLock()
        self._save_lock = threading.Lock()

        self._favorites: List[Dict[str, Any]] = []
        self._fav_ids: set[str] = set()
        self._playlists: List[Dict[str, Any]] = []
        self._history: List[Dict[str, Any]] = []
        self._play_stats: Dict[str, Dict[str, Any]] = {}
        self._history_max_days: int = DEFAULT_HISTORY_MAX_DAYS
        self._history_max_items: int = DEFAULT_HISTORY_MAX_ITEMS
        self._folders: List[str] = []
        self._last_played: Optional[Dict[str, Any]] = None
        self._dirty_position = False

        self._coalesce_timer = QTimer(self)
        self._coalesce_timer.setSingleShot(True)
        self._coalesce_timer.setInterval(4000)
        self._coalesce_timer.timeout.connect(self._flush_coalesced)

        self.load()

    # =========================================================================
    # PERSISTENCE (ATOMIC + CORRUPTION SAFE)
    # =========================================================================
    def load(self) -> None:
        if not self.store_path.exists():
            return
        try:
            raw_text = self.store_path.read_text(encoding="utf-8")
            if not raw_text.strip():
                return
            data = json.loads(raw_text)
            if not isinstance(data, dict):
                return
        except Exception as exc:
            logger.warning("⚠️ Không đọc được user_collections.json, khởi tạo mặc định: %s", exc)
            return

        with self._lock:
            # 1. Favorites
            fav_list: List[Dict[str, Any]] = []
            fav_ids: set[str] = set()
            for raw in data.get("favorites", []):
                snap = snapshot_media_item(raw)
                if snap and snap["id"] not in fav_ids:
                    fav_ids.add(snap["id"])
                    fav_list.append(snap)
            self._favorites = fav_list
            self._fav_ids = fav_ids

            # 2. Playlists
            pl_list: List[Dict[str, Any]] = []
            seen_pids: set[str] = set()
            for raw_pl in data.get("playlists", []):
                if not isinstance(raw_pl, dict):
                    continue
                pid = str(raw_pl.get("id") or f"pl_{uuid.uuid4().hex[:8]}")
                if pid in seen_pids:
                    continue
                name = str(raw_pl.get("name") or "").strip()
                if not name:
                    continue
                seen_pids.add(pid)
                items: List[Dict[str, Any]] = []
                seen_mids: set[str] = set()
                for raw_item in raw_pl.get("items", []):
                    snap = snapshot_media_item(raw_item)
                    if snap and snap["id"] not in seen_mids:
                        seen_mids.add(snap["id"])
                        items.append(snap)
                now = time.time()
                pl_list.append({
                    "id": pid,
                    "name": name,
                    "created_at": float(raw_pl.get("created_at") or now),
                    "updated_at": float(raw_pl.get("updated_at") or now),
                    "items": items,
                })
            self._playlists = pl_list

            # 3. History settings & entries
            h_cfg = data.get("history_settings", {})
            if isinstance(h_cfg, dict):
                try:
                    days = int(h_cfg.get("max_days", DEFAULT_HISTORY_MAX_DAYS))
                except (TypeError, ValueError):
                    days = DEFAULT_HISTORY_MAX_DAYS
                try:
                    items_cap = int(h_cfg.get("max_items", DEFAULT_HISTORY_MAX_ITEMS))
                except (TypeError, ValueError):
                    items_cap = DEFAULT_HISTORY_MAX_ITEMS
                self._history_max_days = max(0, days)
                self._history_max_items = max(1, items_cap)

            hist_list: List[Dict[str, Any]] = []
            seen_hist_ids: set[str] = set()
            raw_hist = data.get("history", [])
            if isinstance(raw_hist, list):
                sorted_raw = sorted(
                    (entry for entry in raw_hist if isinstance(entry, dict)),
                    key=lambda x: float(x.get("watched_at") or 0.0),
                    reverse=True,
                )
                for entry in sorted_raw:
                    snap = snapshot_media_item(entry)
                    if not snap or snap["id"] in seen_hist_ids:
                        continue
                    seen_hist_ids.add(snap["id"])
                    try:
                        watched_at = float(entry.get("watched_at") or time.time())
                    except (TypeError, ValueError):
                        watched_at = time.time()
                    date_key = str(entry.get("date_key") or "").strip()
                    if not date_key:
                        date_key = datetime.fromtimestamp(watched_at).strftime("%Y-%m-%d")
                    try:
                        watch_count = max(1, int(entry.get("watch_count") or 1))
                    except (TypeError, ValueError):
                        watch_count = 1
                    rec = dict(snap)
                    rec["watched_at"] = watched_at
                    rec["date_key"] = date_key
                    rec["watch_count"] = watch_count
                    hist_list.append(rec)
            self._history = hist_list
            pruned = self._prune_history_locked()

            # 3.5. Play Stats (independent of History clear/retention; auto-seeded from existing history if missing)
            stats_map: Dict[str, Dict[str, Any]] = {}
            raw_stats = data.get("play_stats")
            seeded_from_history = False
            if isinstance(raw_stats, dict):
                for mid, raw_entry in raw_stats.items():
                    if not isinstance(raw_entry, dict):
                        continue
                    snap = snapshot_media_item(raw_entry)
                    if not snap:
                        continue
                    try:
                        pcount = max(1, int(raw_entry.get("play_count") or 1))
                    except (TypeError, ValueError):
                        pcount = 1
                    try:
                        listen_sec = max(0.0, float(raw_entry.get("total_listen_sec") or 0.0))
                    except (TypeError, ValueError):
                        listen_sec = 0.0
                    try:
                        last_at = float(raw_entry.get("last_played_at") or time.time())
                    except (TypeError, ValueError):
                        last_at = time.time()
                    try:
                        first_at = float(raw_entry.get("first_played_at") or last_at)
                    except (TypeError, ValueError):
                        first_at = last_at
                    daily_clean: Dict[str, int] = {}
                    raw_daily = raw_entry.get("daily_plays")
                    if isinstance(raw_daily, dict):
                        for dk, cnt in raw_daily.items():
                            try:
                                c_val = int(cnt)
                                if dk and c_val > 0:
                                    daily_clean[str(dk)] = c_val
                            except (TypeError, ValueError):
                                pass
                    rec = dict(snap)
                    rec["play_count"] = pcount
                    rec["total_listen_sec"] = round(listen_sec, 1)
                    rec["last_played_at"] = last_at
                    rec["first_played_at"] = first_at
                    rec["daily_plays"] = daily_clean
                    stats_map[snap["id"]] = rec
            elif self._history:
                # Seamless upgrade: seed initial play_stats from existing history entries
                for entry in self._history:
                    mid = entry["id"]
                    wc = max(1, int(entry.get("watch_count") or 1))
                    ts = float(entry.get("watched_at") or time.time())
                    dk = str(entry.get("date_key") or datetime.fromtimestamp(ts).strftime("%Y-%m-%d"))
                    rec = {
                        "id": mid,
                        "path": entry.get("path", ""),
                        "title": entry.get("title", "Unknown"),
                        "artist": entry.get("artist", "Unknown Artist"),
                        "duration": float(entry.get("duration") or 0.0),
                        "thumbnail": entry.get("thumbnail"),
                        "mtime": entry.get("mtime"),
                        "play_count": wc,
                        "total_listen_sec": 0.0,
                        "last_played_at": ts,
                        "first_played_at": ts,
                        "daily_plays": {dk: wc},
                    }
                    stats_map[mid] = rec
                seeded_from_history = bool(stats_map)
            self._play_stats = stats_map
            stats_pruned = self._prune_play_stats_locked()

            # 4. Folders
            folders_out: List[str] = []
            seen_fkeys: set[str] = set()
            for fp in data.get("folders", []):
                cleaned = _clean_folder_display(str(fp))
                if not cleaned:
                    continue
                fkey = _norm_folder_key(cleaned)
                if fkey not in seen_fkeys:
                    seen_fkeys.add(fkey)
                    folders_out.append(cleaned)
            self._folders = folders_out

            # 5. Last Played
            lp = data.get("last_played")
            if isinstance(lp, dict):
                snap = snapshot_media_item(lp.get("media"))
                if snap:
                    try:
                        pos_ms = max(0, int(lp.get("position_ms") or 0))
                    except (TypeError, ValueError):
                        pos_ms = 0
                    try:
                        updated_at = float(lp.get("updated_at") or time.time())
                    except (TypeError, ValueError):
                        updated_at = time.time()
                    self._last_played = {
                        "media": snap,
                        "position_ms": pos_ms,
                        "updated_at": updated_at,
                    }

        if pruned or seeded_from_history or stats_pruned:
            self.save()

    def _serialize_locked(self) -> bytes:
        payload = {
            "version": SCHEMA_VERSION,
            "favorites": list(self._favorites),
            "playlists": [
                {
                    "id": pl["id"],
                    "name": pl["name"],
                    "created_at": pl["created_at"],
                    "updated_at": pl["updated_at"],
                    "items": list(pl["items"]),
                }
                for pl in self._playlists
            ],
            "history_settings": {
                "max_days": self._history_max_days,
                "max_items": self._history_max_items,
            },
            "history": list(self._history),
            "play_stats": {
                mid: {
                    **entry,
                    "daily_plays": dict(entry.get("daily_plays") or {}),
                }
                for mid, entry in self._play_stats.items()
            },
            "folders": list(self._folders),
            "last_played": dict(self._last_played) if self._last_played else None,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

    def save(self) -> bool:
        with self._lock:
            self._dirty_position = False
            raw_bytes = self._serialize_locked()

        with self._save_lock:
            for attempt in range(5):
                try:
                    atomic_bytes(self.store_path, raw_bytes)
                    return True
                except PermissionError:
                    if attempt < 4:
                        time.sleep(0.05)
                    else:
                        logger.error("❌ Không thể ghi user_collections.json do bị khóa quyền truy cập.")
                except Exception as exc:
                    logger.error("❌ Lỗi lưu user_collections.json: %s", exc)
                    break
        return False

    def _flush_coalesced(self) -> None:
        with self._lock:
            if not self._dirty_position:
                return
        self.save()

    def shutdown(self) -> None:
        """Stop timers and flush any pending position update before process exit."""
        if self._coalesce_timer.isActive():
            self._coalesce_timer.stop()
        with self._lock:
            needs_save = self._dirty_position
        if needs_save:
            self.save()

    # =========================================================================
    # ❤️ FAVORITES
    # =========================================================================
    def is_favorite(self, media_id: Optional[str]) -> bool:
        if not media_id:
            return False
        with self._lock:
            return str(media_id) in self._fav_ids

    def set_favorite(self, media_item: Any, favorited: bool) -> bool:
        snap = snapshot_media_item(media_item)
        if not snap:
            return False
        mid = snap["id"]
        changed = False
        with self._lock:
            currently = mid in self._fav_ids
            if favorited and not currently:
                self._fav_ids.add(mid)
                self._favorites.insert(0, snap)
                changed = True
            elif not favorited and currently:
                self._fav_ids.discard(mid)
                self._favorites = [entry for entry in self._favorites if entry["id"] != mid]
                changed = True
        if changed:
            self.save()
            self.favorites_changed.emit()
        return favorited

    def toggle_favorite(self, media_item: Any) -> bool:
        snap = snapshot_media_item(media_item)
        if not snap:
            return False
        with self._lock:
            target = snap["id"] not in self._fav_ids
        return self.set_favorite(snap, target)

    def favorite_count(self) -> int:
        with self._lock:
            return len(self._favorites)

    def get_favorites(self, media_library: Any = None) -> List[MediaMetadata]:
        with self._lock:
            snapshots = list(self._favorites)
        return [resolve_media_item(entry, media_library) for entry in snapshots]

    # =========================================================================
    # 🎵 PERSONAL PLAYLISTS
    # =========================================================================
    def get_playlists(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "id": pl["id"],
                    "name": pl["name"],
                    "created_at": pl["created_at"],
                    "updated_at": pl["updated_at"],
                    "count": len(pl["items"]),
                }
                for pl in self._playlists
            ]

    def get_playlist(self, playlist_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for pl in self._playlists:
                if pl["id"] == playlist_id:
                    return {
                        "id": pl["id"],
                        "name": pl["name"],
                        "created_at": pl["created_at"],
                        "updated_at": pl["updated_at"],
                        "count": len(pl["items"]),
                    }
        return None

    def get_playlist_items(self, playlist_id: str, media_library: Any = None) -> List[MediaMetadata]:
        with self._lock:
            target = next((pl for pl in self._playlists if pl["id"] == playlist_id), None)
            if target is None:
                return []
            snapshots = list(target["items"])
        return [resolve_media_item(entry, media_library) for entry in snapshots]

    def create_playlist(self, name: str) -> Optional[Dict[str, Any]]:
        cleaned = str(name or "").strip()
        if not cleaned:
            return None
        now = time.time()
        new_pl = {
            "id": f"pl_{uuid.uuid4().hex[:10]}",
            "name": cleaned[:80],
            "created_at": now,
            "updated_at": now,
            "items": [],
        }
        with self._lock:
            self._playlists.append(new_pl)
        self.save()
        self.playlists_changed.emit()
        return {
            "id": new_pl["id"],
            "name": new_pl["name"],
            "created_at": new_pl["created_at"],
            "updated_at": new_pl["updated_at"],
            "count": 0,
        }

    def rename_playlist(self, playlist_id: str, new_name: str) -> bool:
        cleaned = str(new_name or "").strip()
        if not cleaned:
            return False
        changed = False
        with self._lock:
            for pl in self._playlists:
                if pl["id"] == playlist_id:
                    if pl["name"] != cleaned[:80]:
                        pl["name"] = cleaned[:80]
                        pl["updated_at"] = time.time()
                        changed = True
                    break
        if changed:
            self.save()
            self.playlists_changed.emit()
        return changed

    def delete_playlist(self, playlist_id: str) -> bool:
        changed = False
        with self._lock:
            before = len(self._playlists)
            self._playlists = [pl for pl in self._playlists if pl["id"] != playlist_id]
            changed = len(self._playlists) != before
        if changed:
            self.save()
            self.playlists_changed.emit()
        return changed

    def add_to_playlist(self, playlist_id: str, media_item: Any) -> bool:
        snap = snapshot_media_item(media_item)
        if not snap:
            return False
        added = False
        with self._lock:
            target = next((pl for pl in self._playlists if pl["id"] == playlist_id), None)
            if target is None:
                return False
            if all(existing["id"] != snap["id"] for existing in target["items"]):
                target["items"].append(snap)
                target["updated_at"] = time.time()
                added = True
        if added:
            self.save()
            self.playlists_changed.emit()
        return added

    def add_many_to_playlist(self, playlist_id: str, media_items: Sequence[Any]) -> int:
        added_count = 0
        with self._lock:
            target = next((pl for pl in self._playlists if pl["id"] == playlist_id), None)
            if target is None:
                return 0
            existing_ids = {entry["id"] for entry in target["items"]}
            for raw in media_items:
                snap = snapshot_media_item(raw)
                if snap and snap["id"] not in existing_ids:
                    existing_ids.add(snap["id"])
                    target["items"].append(snap)
                    added_count += 1
            if added_count > 0:
                target["updated_at"] = time.time()
        if added_count > 0:
            self.save()
            self.playlists_changed.emit()
        return added_count

    def remove_from_playlist(self, playlist_id: str, media_id: str) -> bool:
        removed = False
        with self._lock:
            target = next((pl for pl in self._playlists if pl["id"] == playlist_id), None)
            if target is None:
                return False
            before = len(target["items"])
            target["items"] = [entry for entry in target["items"] if entry["id"] != media_id]
            if len(target["items"]) != before:
                target["updated_at"] = time.time()
                removed = True
        if removed:
            self.save()
            self.playlists_changed.emit()
        return removed

    def move_playlist_item(self, playlist_id: str, from_index: int, to_index: int) -> bool:
        changed = False
        with self._lock:
            target = next((pl for pl in self._playlists if pl["id"] == playlist_id), None)
            if target is None:
                return False
            items = target["items"]
            if not (0 <= from_index < len(items) and 0 <= to_index < len(items)):
                return False
            if from_index != to_index:
                entry = items.pop(from_index)
                items.insert(to_index, entry)
                target["updated_at"] = time.time()
                changed = True
        if changed:
            self.save()
            self.playlists_changed.emit()
        return changed

    # =========================================================================
    # 🕒 WATCH HISTORY (DATE-GROUPED + BOUNDED RETENTION)
    # =========================================================================
    @property
    def history_max_days(self) -> int:
        with self._lock:
            return self._history_max_days

    @property
    def history_max_items(self) -> int:
        with self._lock:
            return self._history_max_items

    def set_history_limits(
        self,
        max_days: Optional[int] = None,
        max_items: Optional[int] = None,
        now: Optional[float] = None,
    ) -> None:
        changed = False
        with self._lock:
            if max_days is not None:
                val_days = max(0, int(max_days))
                if val_days != self._history_max_days:
                    self._history_max_days = val_days
                    changed = True
            if max_items is not None:
                val_items = max(1, int(max_items))
                if val_items != self._history_max_items:
                    self._history_max_items = val_items
                    changed = True
            if self._prune_history_locked(now=now):
                changed = True
        if changed:
            self.save()
            self.history_changed.emit()

    def _prune_history_locked(self, now: Optional[float] = None) -> bool:
        before_len = len(self._history)
        ref_now = float(now if now is not None else time.time())
        filtered = self._history
        if self._history_max_days > 0:
            cutoff = ref_now - (self._history_max_days * 86400.0)
            filtered = [entry for entry in filtered if float(entry.get("watched_at") or 0.0) >= cutoff]
        filtered.sort(key=lambda entry: float(entry.get("watched_at") or 0.0), reverse=True)
        if self._history_max_items > 0 and len(filtered) > self._history_max_items:
            filtered = filtered[: self._history_max_items]
        changed = len(filtered) != before_len or filtered != self._history
        self._history = filtered
        return changed

    def record_history(self, media_item: Any, watched_at: Optional[float] = None) -> bool:
        snap = snapshot_media_item(media_item)
        if not snap:
            return False
        ts = float(watched_at if watched_at is not None else time.time())
        date_key = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")

        with self._lock:
            prev_count = 0
            prev_thumb = None
            prev_dur = 0.0
            kept: List[Dict[str, Any]] = []
            for entry in self._history:
                if entry["id"] == snap["id"]:
                    prev_count = max(prev_count, int(entry.get("watch_count") or 1))
                    prev_thumb = prev_thumb or entry.get("thumbnail")
                    prev_dur = max(prev_dur, float(entry.get("duration") or 0.0))
                else:
                    kept.append(entry)

            rec = dict(snap)
            if not rec.get("thumbnail") and prev_thumb:
                rec["thumbnail"] = prev_thumb
            if (not rec.get("duration")) and prev_dur > 0:
                rec["duration"] = prev_dur
            rec["watched_at"] = ts
            rec["date_key"] = date_key
            rec["watch_count"] = prev_count + 1

            kept.insert(0, rec)
            self._history = kept
            ref_now = max(ts, time.time()) if watched_at is None else max(
                ts, max((float(x.get("watched_at") or 0.0) for x in self._history), default=ts)
            )
            self._prune_history_locked(now=ref_now)

        self.save()
        self.history_changed.emit()
        return True

    def remove_history_item(self, media_id: str) -> bool:
        removed = False
        with self._lock:
            before = len(self._history)
            self._history = [entry for entry in self._history if entry["id"] != media_id]
            removed = len(self._history) != before
        if removed:
            self.save()
            self.history_changed.emit()
        return removed

    def clear_history(self) -> bool:
        with self._lock:
            if not self._history:
                return False
            self._history = []
        self.save()
        self.history_changed.emit()
        return True

    # =========================================================================
    # 🔥 TOP MOST PLAYED / LISTENING STATS
    # =========================================================================
    def _prune_play_stats_locked(self, ref_date: Optional[date] = None) -> bool:
        changed = False
        cutoff_day = (ref_date or datetime.now().date()) - timedelta(days=MAX_DAILY_PLAY_DAYS)
        cutoff_key = cutoff_day.strftime("%Y-%m-%d")
        for entry in self._play_stats.values():
            daily = entry.get("daily_plays")
            if isinstance(daily, dict) and daily:
                stale = [dk for dk in daily if dk < cutoff_key]
                for dk in stale:
                    del daily[dk]
                    changed = True
        if len(self._play_stats) > MAX_PLAY_STATS_ENTRIES:
            ordered = sorted(
                self._play_stats.items(),
                key=lambda kv: (
                    int(kv[1].get("play_count") or 0),
                    float(kv[1].get("total_listen_sec") or 0.0),
                    float(kv[1].get("last_played_at") or 0.0),
                ),
                reverse=True,
            )
            self._play_stats = dict(ordered[:MAX_PLAY_STATS_ENTRIES])
            changed = True
        return changed

    def record_play_stat(
        self,
        media_item: Any,
        played_at: Optional[float] = None,
        initial_listen_sec: float = 0.0,
    ) -> bool:
        """Increment persistent play counter & daily play rollup (independent of History deletion)."""
        snap = snapshot_media_item(media_item)
        if not snap:
            return False
        ts = float(played_at if played_at is not None else time.time())
        dt = datetime.fromtimestamp(ts)
        date_key = dt.strftime("%Y-%m-%d")
        mid = snap["id"]
        init_sec = round(max(0.0, float(initial_listen_sec or 0.0)), 1)

        with self._lock:
            existing = self._play_stats.get(mid)
            if existing is None:
                rec = dict(snap)
                rec["play_count"] = 1
                rec["total_listen_sec"] = init_sec
                rec["last_played_at"] = ts
                rec["first_played_at"] = ts
                rec["daily_plays"] = {date_key: 1}
                self._play_stats[mid] = rec
            else:
                if snap.get("thumbnail"):
                    existing["thumbnail"] = snap["thumbnail"]
                if snap.get("duration") and snap["duration"] > 0:
                    existing["duration"] = snap["duration"]
                if snap.get("path"):
                    existing["path"] = snap["path"]
                if snap.get("title"):
                    existing["title"] = snap["title"]
                if snap.get("artist"):
                    existing["artist"] = snap["artist"]
                existing["play_count"] = int(existing.get("play_count") or 0) + 1
                if init_sec > 0.0:
                    existing["total_listen_sec"] = round(
                        float(existing.get("total_listen_sec") or 0.0) + init_sec, 1
                    )
                existing["last_played_at"] = max(ts, float(existing.get("last_played_at") or 0.0))
                daily = existing.setdefault("daily_plays", {})
                daily[date_key] = int(daily.get(date_key) or 0) + 1
            self._prune_play_stats_locked(ref_date=dt.date())

        self.save()
        self.stats_changed.emit()
        return True

    def add_listen_seconds(self, media_id: str, delta_sec: float) -> None:
        """Accumulate real listened time (clamped to <= 5s per sample so seeking never inflates stats)."""
        if not media_id:
            return
        clamped = float(delta_sec or 0.0)
        if clamped <= 0.0 or clamped > 5.0:
            return
        with self._lock:
            entry = self._play_stats.get(str(media_id))
            if entry is None:
                return
            entry["total_listen_sec"] = round(float(entry.get("total_listen_sec") or 0.0) + clamped, 1)
            self._dirty_position = True
        if not self._coalesce_timer.isActive():
            self._coalesce_timer.start()

    def remove_play_stat(self, media_id: str) -> bool:
        removed = False
        with self._lock:
            if str(media_id) in self._play_stats:
                del self._play_stats[str(media_id)]
                removed = True
        if removed:
            self.save()
            self.stats_changed.emit()
        return removed

    def reset_play_stats(self) -> bool:
        with self._lock:
            if not self._play_stats:
                return False
            self._play_stats.clear()
        self.save()
        self.stats_changed.emit()
        return True

    def play_stats_count(self) -> int:
        with self._lock:
            return len(self._play_stats)

    def _effective_play_count(self, entry: Dict[str, Any], period: str, ref_today: date) -> int:
        if period == "all":
            return max(0, int(entry.get("play_count") or 0))
        days = 7 if period == "7d" else 30 if period == "30d" else 0
        if days <= 0:
            return max(0, int(entry.get("play_count") or 0))
        cutoff_key = (ref_today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        daily = entry.get("daily_plays")
        if not isinstance(daily, dict):
            return 0
        return sum(int(cnt) for dk, cnt in daily.items() if dk >= cutoff_key and int(cnt) > 0)

    def get_top_tracks(
        self,
        period: str = "all",
        limit: int = 100,
        query: str = "",
        media_library: Any = None,
        today: Optional[date] = None,
    ) -> List[TopTrackView]:
        """Return ranked TopTrackView list for period in {'all', '30d', '7d'}."""
        ref_today = today or datetime.now().date()
        q = str(query or "").strip().lower()
        with self._lock:
            raw_entries = [
                (dict(entry), dict(entry.get("daily_plays") or {}))
                for entry in self._play_stats.values()
            ]

        scored: List[Tuple[int, float, float, MediaMetadata]] = []
        for entry, daily in raw_entries:
            entry["daily_plays"] = daily
            plays = self._effective_play_count(entry, period, ref_today)
            if plays <= 0:
                continue
            media = resolve_media_item(entry, media_library)
            if q and q not in media.title.lower() and q not in (media.artist or "").lower():
                continue
            listen_sec = float(entry.get("total_listen_sec") or 0.0)
            last_at = float(entry.get("last_played_at") or 0.0)
            scored.append((plays, listen_sec, last_at, media))

        scored.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
        if limit > 0:
            scored = scored[:limit]
        max_plays = scored[0][0] if scored else 1
        return [
            TopTrackView(
                rank=idx + 1,
                media=media,
                play_count=plays,
                total_listen_sec=listen_sec,
                last_played_at=last_at,
                share_ratio=max(0.08, min(1.0, plays / float(max(1, max_plays)))),
            )
            for idx, (plays, listen_sec, last_at, media) in enumerate(scored)
        ]

    def get_listening_summary(
        self,
        period: str = "all",
        media_library: Any = None,
        today: Optional[date] = None,
    ) -> Dict[str, Any]:
        """Aggregate summary metrics for the Top Tracks hero banner."""
        top_all = self.get_top_tracks(period=period, limit=0, media_library=media_library, today=today)
        total_plays = sum(item.play_count for item in top_all)
        total_listen_sec = sum(item.total_listen_sec for item in top_all)
        artist_plays: Dict[str, int] = {}
        for item in top_all:
            artist = (item.media.artist or "").strip()
            if artist and artist.lower() != "unknown artist":
                artist_plays[artist] = artist_plays.get(artist, 0) + item.play_count
        top_artist = ""
        top_artist_plays = 0
        if artist_plays:
            top_artist, top_artist_plays = max(artist_plays.items(), key=lambda kv: kv[1])
        return {
            "track_count": len(top_all),
            "total_plays": total_plays,
            "total_listen_sec": total_listen_sec,
            "top_artist": top_artist,
            "top_artist_plays": top_artist_plays,
        }

    def history_count(self) -> int:
        with self._lock:
            return len(self._history)

    def get_history_items(self, media_library: Any = None) -> List[MediaMetadata]:
        with self._lock:
            snapshots = list(self._history)
        return [resolve_media_item(entry, media_library) for entry in snapshots]

    def get_history_grouped(
        self,
        query: str = "",
        media_library: Any = None,
        today: Optional[date] = None,
    ) -> List[Tuple[str, str, List[HistoryItemView]]]:
        """Return [(section_label, date_key, [HistoryItemView, ...]), ...] ordered newest first."""
        with self._lock:
            snapshots = list(self._history)

        q = str(query or "").strip().lower()
        ref_today = today or datetime.now().date()
        groups: Dict[str, List[HistoryItemView]] = {}
        group_order: List[str] = []
        label_cache: Dict[str, str] = {}

        for entry in snapshots:
            media = resolve_media_item(entry, media_library)
            watched_at = float(entry.get("watched_at") or 0.0)
            dt = datetime.fromtimestamp(watched_at)
            date_key = str(entry.get("date_key") or dt.strftime("%Y-%m-%d"))
            time_text = dt.strftime("%H:%M")
            section_label = label_cache.get(date_key)
            if section_label is None:
                section_label = format_date_section_label(date_key, today=ref_today)
                label_cache[date_key] = section_label

            if q:
                haystack = f"{media.title} {media.artist} {section_label} {time_text}".lower()
                if q not in haystack:
                    continue

            view = HistoryItemView(
                media=media,
                watched_at=watched_at,
                date_key=date_key,
                time_text=time_text,
                watch_count=max(1, int(entry.get("watch_count") or 1)),
            )
            if date_key not in groups:
                groups[date_key] = []
                group_order.append(date_key)
            groups[date_key].append(view)

        return [(label_cache[dk], dk, groups[dk]) for dk in group_order]

    # =========================================================================
    # 📂 MULTI-FOLDER SOURCES
    # =========================================================================
    def get_folders(self) -> List[str]:
        with self._lock:
            return list(self._folders)

    def sync_legacy_last_folder(self, legacy_folder: Optional[str]) -> List[str]:
        """Seed multi-folder list from legacy ConfigManager.last_folder if non-empty."""
        cleaned = _clean_folder_display(legacy_folder or "")
        if not cleaned:
            return self.get_folders()
        added = False
        with self._lock:
            fkey = _norm_folder_key(cleaned)
            existing_keys = {_norm_folder_key(p) for p in self._folders}
            if fkey not in existing_keys:
                self._folders.insert(0, cleaned)
                added = True
        if added:
            self.save()
            self.folders_changed.emit()
        return self.get_folders()

    def add_folder(self, folder_path: str) -> bool:
        cleaned = _clean_folder_display(folder_path)
        if not cleaned:
            return False
        added = False
        with self._lock:
            fkey = _norm_folder_key(cleaned)
            if all(_norm_folder_key(p) != fkey for p in self._folders):
                self._folders.append(cleaned)
                added = True
        if added:
            self.save()
            self.folders_changed.emit()
        return added

    def remove_folder(self, folder_path: str) -> bool:
        cleaned = _clean_folder_display(folder_path)
        if not cleaned:
            return False
        fkey = _norm_folder_key(cleaned)
        removed = False
        with self._lock:
            before = len(self._folders)
            self._folders = [p for p in self._folders if _norm_folder_key(p) != fkey]
            removed = len(self._folders) != before
        if removed:
            self.save()
            self.folders_changed.emit()
        return removed

    # =========================================================================
    # ▶️ SMART RESUME / LAST-PLAYED SESSION
    # =========================================================================
    def get_last_played(self, media_library: Any = None) -> Optional[Tuple[MediaMetadata, int, float]]:
        """Return (MediaMetadata, position_ms, updated_at) or None."""
        with self._lock:
            if not self._last_played:
                return None
            snap = dict(self._last_played["media"])
            pos_ms = int(self._last_played.get("position_ms") or 0)
            updated_at = float(self._last_played.get("updated_at") or 0.0)
        return resolve_media_item(snap, media_library), pos_ms, updated_at

    def record_last_played_track(self, media_item: Any, position_ms: int = 0) -> None:
        snap = snapshot_media_item(media_item)
        if not snap:
            return
        with self._lock:
            # Preserve previous position only if re-selecting the exact same track at position 0?
            # No: explicit click starts from 0 unless caller specifies position_ms.
            self._last_played = {
                "media": snap,
                "position_ms": max(0, int(position_ms)),
                "updated_at": time.time(),
            }
            self._dirty_position = True
        if not self._coalesce_timer.isActive():
            self._coalesce_timer.start()
        self.last_played_changed.emit()

    def update_last_played_position(self, position_ms: int) -> None:
        """RAM-only fast path during playback; coalesced to disk every 4 seconds."""
        pos = max(0, int(position_ms))
        with self._lock:
            if not self._last_played:
                return
            if abs(int(self._last_played.get("position_ms") or 0) - pos) < 1000:
                return
            self._last_played["position_ms"] = pos
            self._last_played["updated_at"] = time.time()
            self._dirty_position = True
        if not self._coalesce_timer.isActive():
            self._coalesce_timer.start()

    def refresh_media_thumbnail(self, media_id: str, thumb_path: str) -> None:
        """Keep snapshots up-to-date when background ThumbnailWorker discovers a cover."""
        if not media_id or not thumb_path:
            return
        dirty = False
        with self._lock:
            for entry in self._favorites:
                if entry["id"] == media_id and entry.get("thumbnail") != thumb_path:
                    entry["thumbnail"] = thumb_path
                    dirty = True
            for pl in self._playlists:
                for entry in pl["items"]:
                    if entry["id"] == media_id and entry.get("thumbnail") != thumb_path:
                        entry["thumbnail"] = thumb_path
                        dirty = True
            for entry in self._history:
                if entry["id"] == media_id and entry.get("thumbnail") != thumb_path:
                    entry["thumbnail"] = thumb_path
                    dirty = True
            stat_entry = self._play_stats.get(media_id)
            if stat_entry is not None and stat_entry.get("thumbnail") != thumb_path:
                stat_entry["thumbnail"] = thumb_path
                dirty = True
            if self._last_played and self._last_played["media"]["id"] == media_id:
                if self._last_played["media"].get("thumbnail") != thumb_path:
                    self._last_played["media"]["thumbnail"] = thumb_path
                    dirty = True
            if dirty:
                self._dirty_position = True
        if dirty and not self._coalesce_timer.isActive():
            self._coalesce_timer.start()
