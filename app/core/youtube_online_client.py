"""Isolated YouTube Online data engine (InnerTube + yt-dlp read-only) & local profile store.

Strictly additive module: never mutates offline MediaLibrary, user_collections, or setting.json.
All network reads are strictly read-only with gentle pacing; user subscriptions, likes,
saved online playlists, watch history, and search history live safely in a dedicated
local JSON file (`storage/youtube-online-profile.json`).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import html
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Any, Callable
import urllib.parse

from control.worker_lifecycle import OwnedProcesses
from download_core.studio_download_engine import (
    normalize_cookies_browser,
    resolve_ytdlp_executable,
)
from paths import storage_dir

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
_INNERTUBE_CLIENT_VERSION = "2.20250501.00.00"
_INNERTUBE_BASE = "https://www.youtube.com/youtubei/v1"
_SUGGEST_URL = "https://suggestqueries.google.com/complete/search"
_MUSIC_HUB_CHANNEL_ID = "UC-9-kyTW8ZkZNDHQJ6FgpwQ"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Canonical YouTube search filter protobuf params (safe public web filters)
SEARCH_FILTER_PARAMS: dict[str, str] = {
    "all": "",
    "videos": "EgIQAQ%3D%3D",
    "playlists": "EgIQAw%3D%3D",
    "channels": "EgIQAg%3D%3D",
    "live": "EgJAAQ%3D%3D",
    "music": "EgIQAQ%3D%3D",
}

TOPIC_CHIPS: tuple[tuple[str, str, str, str], ...] = (
    ("all", "Tất cả", "All", ""),
    ("music", "Âm nhạc", "Music", ""),
    ("mixes", "Mix đề xuất", "Mixes", "music mix playlist official audio"),
    ("vpop", "Nhạc Việt", "V-Pop", "nhạc việt mới hay nhất official mv"),
    ("lofi", "Lo-Fi & Chill", "Lo-Fi & Chill", "lofi hip hop chill beats"),
    ("acoustic", "Acoustic", "Acoustic", "acoustic ballad cover live session"),
    ("gaming", "Gaming", "Gaming", "gaming soundtrack official trailer"),
    ("podcast", "Podcast", "Podcast", "podcast tiếng việt nổi bật"),
    ("live", "Trực tiếp", "Live", "live music radio 24/7"),
)

_RE_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_RE_TIMESTAMP = re.compile(r"(?:^|[\s(\[-])(\d{1,2}:\d{2}(?::\d{2})?)\b")
_RE_VTT_CUE_TIME = re.compile(
    r"(?P<sh>\d{1,2}:)?(?P<sm>\d{2}):(?P<ss>\d{2})[.,](?P<sms>\d{3})\s*-->\s*"
    r"(?P<eh>\d{1,2}:)?(?P<em>\d{2}):(?P<es>\d{2})[.,](?P<ems>\d{3})"
)
_RE_HTML_TAG = re.compile(r"<[^>]+>")


@dataclass
class OnlineVideoItem:
    video_id: str
    title: str
    channel_name: str = ""
    channel_id: str = ""
    channel_avatar: str = ""
    thumbnail_url: str = ""
    duration_text: str = ""
    duration_sec: int = 0
    views_text: str = ""
    published_text: str = ""
    is_live: bool = False
    item_type: str = "video"  # 'video' | 'playlist' | 'channel'
    playlist_id: str = ""
    video_count_text: str = ""
    description_snippet: str = ""

    @property
    def watch_url(self) -> str:
        if self.item_type == "playlist" and self.playlist_id:
            return f"https://www.youtube.com/playlist?list={self.playlist_id}"
        if self.item_type == "channel" and self.channel_id:
            return f"https://www.youtube.com/channel/{self.channel_id}"
        if self.video_id:
            base = f"https://www.youtube.com/watch?v={self.video_id}"
            if self.playlist_id:
                return f"{base}&list={self.playlist_id}"
            return base
        return ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OnlineVideoItem":
        if not isinstance(data, dict):
            return cls(video_id="", title="")
        return cls(
            video_id=str(data.get("video_id") or ""),
            title=str(data.get("title") or ""),
            channel_name=str(data.get("channel_name") or ""),
            channel_id=str(data.get("channel_id") or ""),
            channel_avatar=str(data.get("channel_avatar") or ""),
            thumbnail_url=str(data.get("thumbnail_url") or ""),
            duration_text=str(data.get("duration_text") or ""),
            duration_sec=int(data.get("duration_sec") or 0),
            views_text=str(data.get("views_text") or ""),
            published_text=str(data.get("published_text") or ""),
            is_live=bool(data.get("is_live", False)),
            item_type=str(data.get("item_type") or "video"),
            playlist_id=str(data.get("playlist_id") or ""),
            video_count_text=str(data.get("video_count_text") or ""),
            description_snippet=str(data.get("description_snippet") or ""),
        )


@dataclass
class OnlineChapter:
    title: str
    start_sec: float
    end_sec: float = 0.0


@dataclass
class OnlineComment:
    comment_id: str
    author: str
    author_channel_id: str = ""
    avatar_url: str = ""
    text: str = ""
    published_text: str = ""
    likes_text: str = ""
    replies_text: str = ""
    is_creator: bool = False


@dataclass
class OnlineSubtitleTrack:
    lang_code: str
    label: str
    url: str
    ext: str = "vtt"
    is_auto: bool = False


@dataclass
class OnlineSubtitleCue:
    start_ms: int
    end_ms: int
    text: str


@dataclass
class OnlineWatchInfo:
    video_id: str
    title: str = ""
    channel_name: str = ""
    channel_id: str = ""
    channel_avatar: str = ""
    subscriber_text: str = ""
    views_text: str = ""
    published_text: str = ""
    likes_text: str = ""
    description: str = ""
    chapters: list[OnlineChapter] = field(default_factory=list)
    related: list[OnlineVideoItem] = field(default_factory=list)
    mix_items: list[OnlineVideoItem] = field(default_factory=list)
    comment_token: str = ""
    is_live: bool = False


@dataclass
class OnlineChannelInfo:
    channel_id: str
    name: str
    handle: str = ""
    avatar_url: str = ""
    subscriber_text: str = ""
    description: str = ""
    items: list[OnlineVideoItem] = field(default_factory=list)


@dataclass
class ResolvedStream:
    video_id: str
    title: str
    channel_name: str = ""
    channel_id: str = ""
    duration_sec: float = 0.0
    thumbnail_url: str = ""
    audio_url: str = ""
    audio_codec: str = ""
    audio_abr: float = 0.0
    audio_sr: int = 48000
    video_streams: dict[str, dict[str, Any]] = field(default_factory=dict)
    progressive_url: str = ""
    http_headers: dict[str, str] = field(default_factory=dict)
    chapters: list[OnlineChapter] = field(default_factory=list)
    subtitles: list[OnlineSubtitleTrack] = field(default_factory=list)
    resolved_at_mono: float = 0.0
    is_live: bool = False


# =====================================================================
# URL / DURATION / TEXT PARSING HELPERS
# =====================================================================

def parse_duration_text(text: str) -> int:
    """Convert '3:45' or '1:02:18' into integer seconds."""
    raw = str(text or "").strip()
    if not raw or ":" not in raw:
        return 0
    parts = raw.split(":")
    try:
        nums = [int(p.strip()) for p in parts]
    except ValueError:
        return 0
    if len(nums) == 2:
        return max(0, nums[0] * 60 + nums[1])
    if len(nums) == 3:
        return max(0, nums[0] * 3600 + nums[1] * 60 + nums[2])
    return 0


def format_seconds_mmss(sec: float | int) -> str:
    total = max(0, int(round(float(sec or 0))))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def parse_youtube_input(raw: str) -> dict[str, str] | None:
    """Detect whether text is a direct YouTube video, playlist, or channel URL/ID."""
    text = str(raw or "").strip()
    if not text:
        return None
    if _RE_VIDEO_ID.match(text):
        return {"kind": "video", "video_id": text}

    if not re.match(r"^https?://", text, re.IGNORECASE):
        if any(dom in text.lower() for dom in ("youtube.com/", "youtu.be/", "music.youtube.com/")):
            text = "https://" + text
        else:
            return None

    try:
        parsed = urllib.parse.urlparse(text)
    except Exception:
        return None
    host = (parsed.hostname or "").lower()
    if not (
        host == "youtu.be"
        or host.endswith(".youtube.com")
        or host == "youtube.com"
        or host.endswith(".youtube-nocookie.com")
    ):
        return None

    qs = urllib.parse.parse_qs(parsed.query)
    path = parsed.path.strip("/")
    list_id = (qs.get("list") or [""])[0].strip()

    if host == "youtu.be":
        vid = path.split("/")[0] if path else ""
        if _RE_VIDEO_ID.match(vid):
            return {"kind": "video", "video_id": vid, "playlist_id": list_id}
        return None

    if path == "watch":
        vid = (qs.get("v") or [""])[0].strip()
        if _RE_VIDEO_ID.match(vid):
            return {"kind": "video", "video_id": vid, "playlist_id": list_id}
        if list_id:
            return {"kind": "playlist", "playlist_id": list_id, "url": text}
    if path.startswith(("shorts/", "embed/", "live/")):
        parts = path.split("/")
        if len(parts) >= 2 and _RE_VIDEO_ID.match(parts[1]):
            return {"kind": "video", "video_id": parts[1], "playlist_id": list_id}
    if path == "playlist" and list_id:
        return {"kind": "playlist", "playlist_id": list_id, "url": text}
    if list_id and not path:
        return {"kind": "playlist", "playlist_id": list_id, "url": text}
    if path.startswith("channel/"):
        cid = path.split("/")[1]
        if cid:
            return {"kind": "channel", "channel_id": cid, "url": text}
    if path.startswith("@") or path.startswith(("c/", "user/")):
        return {"kind": "channel", "channel_id": "", "url": text}
    return None


def parse_chapters_from_description(description: str, duration_sec: float = 0.0) -> list[OnlineChapter]:
    """Extract chapter markers from timestamped YouTube descriptions."""
    if not description:
        return []
    found: list[tuple[float, str]] = []
    for line in str(description).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = _RE_TIMESTAMP.search(stripped)
        if not m:
            continue
        ts_str = m.group(1)
        sec = float(parse_duration_text(ts_str))
        # Clean surrounding timestamp & dash separators
        title = (stripped[: m.start(1)] + stripped[m.end(1) :]).strip(" \t-–—:|•[]()")
        if title:
            found.append((sec, title))
    if len(found) < 2:
        return []
    # Deduplicate and ensure monotonic ascending order
    found.sort(key=lambda x: x[0])
    chapters: list[OnlineChapter] = []
    seen_sec: set[int] = set()
    for sec, title in found:
        key = int(sec)
        if key in seen_sec:
            continue
        seen_sec.add(key)
        chapters.append(OnlineChapter(title=title[:120], start_sec=sec))
    for idx, ch in enumerate(chapters):
        if idx + 1 < len(chapters):
            ch.end_sec = chapters[idx + 1].start_sec
        elif duration_sec > ch.start_sec:
            ch.end_sec = float(duration_sec)
    return chapters


def parse_json3_subtitles(raw_text: str) -> list[OnlineSubtitleCue]:
    """Parse YouTube json3 timed-text payload into clean sorted cues."""
    try:
        payload = json.loads(raw_text)
    except (ValueError, TypeError):
        return []
    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        return []
    cues: list[OnlineSubtitleCue] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        segs = ev.get("segs")
        if not isinstance(segs, list):
            continue
        text = "".join(str(s.get("utf8") or "") for s in segs if isinstance(s, dict))
        text = html.unescape(text).replace("\r", "")
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if not text:
            continue
        start_ms = max(0, int(ev.get("tStartMs") or 0))
        dur_ms = int(ev.get("dDurationMs") or 2500)
        end_ms = max(start_ms + 300, start_ms + max(300, dur_ms))
        cues.append(OnlineSubtitleCue(start_ms=start_ms, end_ms=end_ms, text=text))
    cues.sort(key=lambda c: c.start_ms)
    # Trim overlapping rolling auto-caption end times cleanly
    for i in range(len(cues) - 1):
        if cues[i].end_ms > cues[i + 1].start_ms:
            cues[i].end_ms = max(cues[i].start_ms + 200, cues[i + 1].start_ms)
    return cues


def parse_vtt_subtitles(raw_text: str) -> list[OnlineSubtitleCue]:
    """Parse WebVTT / SRT subtitle text into clean sorted cues."""
    if not raw_text:
        return []
    lines = str(raw_text).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cues: list[OnlineSubtitleCue] = []
    i = 0
    n = len(lines)
    while i < n:
        m = _RE_VTT_CUE_TIME.search(lines[i])
        if not m:
            i += 1
            continue
        sh = int(m.group("sh")[:-1]) if m.group("sh") else 0
        sm = int(m.group("sm"))
        ss = int(m.group("ss"))
        sms = int(m.group("sms"))
        eh = int(m.group("eh")[:-1]) if m.group("eh") else 0
        em = int(m.group("em"))
        es = int(m.group("es"))
        ems = int(m.group("ems"))
        start_ms = ((sh * 3600 + sm * 60 + ss) * 1000) + sms
        end_ms = ((eh * 3600 + em * 60 + es) * 1000) + ems
        i += 1
        text_lines: list[str] = []
        while i < n and lines[i].strip():
            cleaned = html.unescape(_RE_HTML_TAG.sub("", lines[i])).strip()
            if cleaned:
                text_lines.append(cleaned)
            i += 1
        text = "\n".join(text_lines).strip()
        if text:
            if cues and cues[-1].text == text and abs(start_ms - cues[-1].end_ms) <= 120:
                cues[-1].end_ms = max(cues[-1].end_ms, end_ms)
            else:
                cues.append(OnlineSubtitleCue(start_ms=start_ms, end_ms=max(start_ms + 250, end_ms), text=text))
    cues.sort(key=lambda c: c.start_ms)
    return cues


# =====================================================================
# INNERTUBE JSON EXTRACTION HELPERS (2024-2026 SCHEMAS)
# =====================================================================

def _extract_text(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if "simpleText" in node and isinstance(node["simpleText"], str):
            return node["simpleText"]
        if "content" in node and isinstance(node["content"], str):
            return node["content"]
        runs = node.get("runs")
        if isinstance(runs, list):
            return "".join(str(r.get("text") or "") for r in runs if isinstance(r, dict))
    return ""


def _best_thumb_url(thumbs: Any, fallback_vid: str = "") -> str:
    sources: list[dict[str, Any]] = []
    if isinstance(thumbs, dict):
        if isinstance(thumbs.get("thumbnails"), list):
            sources = thumbs["thumbnails"]
        elif isinstance(thumbs.get("sources"), list):
            sources = thumbs["sources"]
    elif isinstance(thumbs, list):
        sources = thumbs
    best = ""
    best_w = -1
    for src in sources:
        if not isinstance(src, dict):
            continue
        url = str(src.get("url") or "").strip()
        if not url:
            continue
        if url.startswith("//"):
            url = "https:" + url
        w = int(src.get("width") or 0)
        if w >= best_w:
            best_w = w
            best = url
    if not best and fallback_vid:
        best = f"https://i.ytimg.com/vi/{fallback_vid}/hqdefault.jpg"
    return best


def _walk_nodes(obj: Any, target_keys: set[str], out: list[tuple[str, dict[str, Any]]], limit: int = 80) -> None:
    if len(out) >= limit:
        return
    if isinstance(obj, dict):
        for key in target_keys:
            if key in obj and isinstance(obj[key], dict):
                out.append((key, obj[key]))
                if len(out) >= limit:
                    return
        for val in obj.values():
            if len(out) >= limit:
                return
            _walk_nodes(val, target_keys, out, limit)
    elif isinstance(obj, list):
        for item in obj:
            if len(out) >= limit:
                return
            _walk_nodes(item, target_keys, out, limit)


def _parse_video_renderer(node: dict[str, Any]) -> OnlineVideoItem | None:
    vid = str(node.get("videoId") or "").strip()
    if not _RE_VIDEO_ID.match(vid):
        return None
    title = _extract_text(node.get("title"))
    if not title:
        return None
    owner = node.get("ownerText") or node.get("longBylineText") or node.get("shortBylineText") or {}
    channel_name = _extract_text(owner)
    channel_id = ""
    runs = owner.get("runs") if isinstance(owner, dict) else None
    if isinstance(runs, list):
        for r in runs:
            if isinstance(r, dict):
                bid = (
                    r.get("navigationEndpoint", {})
                    .get("browseEndpoint", {})
                    .get("browseId", "")
                )
                if bid:
                    channel_id = str(bid)
                    break

    avatar = ""
    ch_thumb = node.get("channelThumbnailSupportedRenderers", {}).get(
        "channelThumbnailWithLinkRenderer", {}
    )
    if ch_thumb:
        avatar = _best_thumb_url(ch_thumb.get("thumbnail"))
        if not channel_id:
            channel_id = str(
                ch_thumb.get("navigationEndpoint", {})
                .get("browseEndpoint", {})
                .get("browseId", "")
            )

    dur_text = _extract_text(node.get("lengthText"))
    if not dur_text:
        for ov in node.get("thumbnailOverlays") or []:
            if isinstance(ov, dict) and "thumbnailOverlayTimeStatusRenderer" in ov:
                dur_text = _extract_text(ov["thumbnailOverlayTimeStatusRenderer"].get("text"))
                if dur_text:
                    break
    views_text = _extract_text(node.get("shortViewCountText")) or _extract_text(node.get("viewCountText"))
    pub_text = _extract_text(node.get("publishedTimeText"))
    is_live = False
    for b in node.get("badges") or []:
        lbl = _extract_text(b.get("metadataBadgeRenderer", {}).get("label")) if isinstance(b, dict) else ""
        if lbl.upper() in ("LIVE", "TRỰC TIẾP"):
            is_live = True
    if not dur_text and is_live:
        dur_text = "LIVE"

    snippet = ""
    for sn in node.get("detailedMetadataSnippets") or []:
        if isinstance(sn, dict):
            snippet = _extract_text(sn.get("snippetText"))
            if snippet:
                break

    return OnlineVideoItem(
        video_id=vid,
        title=title.strip(),
        channel_name=channel_name.strip(),
        channel_id=channel_id.strip(),
        channel_avatar=avatar,
        thumbnail_url=_best_thumb_url(node.get("thumbnail"), vid),
        duration_text=dur_text.strip(),
        duration_sec=parse_duration_text(dur_text),
        views_text=views_text.strip(),
        published_text=pub_text.strip(),
        is_live=is_live,
        item_type="video",
        description_snippet=snippet.strip(),
    )


def _parse_lockup_view_model(node: dict[str, Any]) -> OnlineVideoItem | None:
    content_id = str(node.get("contentId") or "").strip()
    content_type = str(node.get("contentType") or "").upper()
    meta = node.get("metadata", {}).get("lockupMetadataViewModel", {})
    title = _extract_text(meta.get("title")).strip()
    if not title:
        return None

    # Thumbnail + duration/count badge
    img_root = node.get("contentImage", {})
    thumb_vm = img_root.get("thumbnailViewModel")
    if not thumb_vm:
        thumb_vm = img_root.get("collectionThumbnailViewModel", {}).get("primaryThumbnail", {}).get("thumbnailViewModel")
    thumb_url = _best_thumb_url((thumb_vm or {}).get("image"))

    badge_text = ""
    for ov in (thumb_vm or {}).get("overlays") or []:
        if not isinstance(ov, dict):
            continue
        badges = (
            ov.get("thumbnailBottomOverlayViewModel", {}).get("badges")
            or ov.get("thumbnailOverlayBadgeViewModel", {}).get("thumbnailBadges")
            or []
        )
        for b in badges:
            if isinstance(b, dict):
                t = _extract_text(b.get("thumbnailBadgeViewModel", {}).get("text"))
                if t:
                    badge_text = t.strip()
                    break
        if badge_text:
            break

    # Avatar + channel ID
    avatar_root = meta.get("image", {}).get("decoratedAvatarViewModel", {})
    avatar_url = _best_thumb_url(avatar_root.get("avatar", {}).get("avatarViewModel", {}).get("image"))
    channel_id = str(
        avatar_root.get("rendererContext", {})
        .get("commandContext", {})
        .get("onTap", {})
        .get("innertubeCommand", {})
        .get("browseEndpoint", {})
        .get("browseId", "")
    ).strip()

    # Metadata rows: [channel_name], [views, published]
    rows = meta.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows") or []
    parts_flat: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for p in row.get("metadataParts") or []:
            if isinstance(p, dict):
                txt = _extract_text(p.get("text")).strip()
                if txt:
                    parts_flat.append(txt)

    channel_name = parts_flat[0] if len(parts_flat) >= 1 else ""
    views_text = parts_flat[1] if len(parts_flat) >= 2 else ""
    pub_text = parts_flat[2] if len(parts_flat) >= 3 else ""

    # Determine video vs playlist
    watch_ep = (
        node.get("rendererContext", {})
        .get("commandContext", {})
        .get("onTap", {})
        .get("innertubeCommand", {})
        .get("watchEndpoint", {})
    )
    watch_vid = str(watch_ep.get("videoId") or "").strip()
    watch_list = str(watch_ep.get("playlistId") or "").strip()

    is_playlist = "PLAYLIST" in content_type or "MIX" in content_type or (
        bool(content_id) and not _RE_VIDEO_ID.match(content_id)
    )

    if is_playlist:
        pl_id = watch_list or content_id
        if not pl_id:
            return None
        return OnlineVideoItem(
            video_id=watch_vid if _RE_VIDEO_ID.match(watch_vid) else "",
            title=title,
            channel_name=channel_name,
            channel_id=channel_id,
            channel_avatar=avatar_url,
            thumbnail_url=thumb_url,
            duration_text=badge_text,
            views_text=views_text,
            published_text=pub_text,
            item_type="playlist",
            playlist_id=pl_id,
            video_count_text=badge_text,
        )

    vid = content_id if _RE_VIDEO_ID.match(content_id) else watch_vid
    if not _RE_VIDEO_ID.match(vid):
        return None
    is_live = badge_text.upper() in ("LIVE", "TRỰC TIẾP")
    return OnlineVideoItem(
        video_id=vid,
        title=title,
        channel_name=channel_name,
        channel_id=channel_id,
        channel_avatar=avatar_url,
        thumbnail_url=thumb_url or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        duration_text=badge_text,
        duration_sec=parse_duration_text(badge_text),
        views_text=views_text,
        published_text=pub_text,
        is_live=is_live,
        item_type="video",
        playlist_id=watch_list,
    )


def _parse_playlist_panel_video(node: dict[str, Any]) -> OnlineVideoItem | None:
    vid = str(node.get("videoId") or "").strip()
    if not _RE_VIDEO_ID.match(vid):
        return None
    title = _extract_text(node.get("title")).strip()
    if not title:
        return None
    dur = _extract_text(node.get("lengthText")).strip()
    owner = node.get("shortBylineText") or node.get("longBylineText") or {}
    ch_name = _extract_text(owner).strip()
    ch_id = ""
    runs = owner.get("runs") if isinstance(owner, dict) else None
    if isinstance(runs, list):
        for r in runs:
            bid = r.get("navigationEndpoint", {}).get("browseEndpoint", {}).get("browseId", "") if isinstance(r, dict) else ""
            if bid:
                ch_id = str(bid)
                break
    return OnlineVideoItem(
        video_id=vid,
        title=title,
        channel_name=ch_name,
        channel_id=ch_id,
        thumbnail_url=_best_thumb_url(node.get("thumbnail"), vid),
        duration_text=dur,
        duration_sec=parse_duration_text(dur),
        item_type="video",
    )


def _parse_channel_renderer(node: dict[str, Any]) -> OnlineVideoItem | None:
    cid = str(node.get("channelId") or "").strip()
    title = _extract_text(node.get("title")).strip()
    if not cid or not title:
        return None
    thumb = _best_thumb_url(node.get("thumbnail"))
    subs = _extract_text(node.get("videoCountText")) or _extract_text(node.get("subscriberCountText"))
    desc = _extract_text(node.get("descriptionSnippet"))
    return OnlineVideoItem(
        video_id="",
        title=title,
        channel_name=title,
        channel_id=cid,
        channel_avatar=thumb,
        thumbnail_url=thumb,
        views_text=subs.strip(),
        description_snippet=desc.strip(),
        item_type="channel",
    )


def _extract_items_from_payload(payload: dict[str, Any], *, limit: int = 36, include_playlists: bool = True, include_channels: bool = True) -> list[OnlineVideoItem]:
    nodes: list[tuple[str, dict[str, Any]]] = []
    keys = {"videoRenderer", "compactVideoRenderer", "gridVideoRenderer", "playlistVideoRenderer", "lockupViewModel"}
    if include_channels:
        keys.add("channelRenderer")
    _walk_nodes(payload, keys, nodes, limit=limit * 2)
    items: list[OnlineVideoItem] = []
    seen: set[str] = set()
    for kind, node in nodes:
        item: OnlineVideoItem | None = None
        if kind == "lockupViewModel":
            item = _parse_lockup_view_model(node)
        elif kind == "channelRenderer":
            item = _parse_channel_renderer(node)
        else:
            item = _parse_video_renderer(node)
        if item is None:
            continue
        if item.item_type == "playlist" and not include_playlists:
            continue
        if item.item_type == "channel" and not include_channels:
            continue
        dedup_key = f"{item.item_type}:{item.video_id or item.playlist_id or item.channel_id}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        items.append(item)
        if len(items) >= limit:
            break
    return items


# =====================================================================
# ISOLATED LOCAL PROFILE STORE (ZERO GOOGLE WRITE RISK)
# =====================================================================

class YouTubeOnlineProfileStore:
    """Thread-safe local profile store for YouTube Online (subscriptions, playlists, likes, history)."""

    DEFAULT_PREFS: dict[str, Any] = {
        "quality": "1080p",
        "audio_only": False,
        "subtitle_mode": "off",  # 'off' | 'youtube_cc' | 'ai_handoff'
        "subtitle_lang": "vi",
        "autoplay": True,
        "speed": 1.0,
        "volume": 0.7,
        "cookies_browser": "",
        "cookies_file": "",
    }

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else (Path(storage_dir()) / "youtube-online-profile.json")
        self._lock = threading.RLock()
        self._data: dict[str, Any] = self._empty_state()
        self.load()

    def _empty_state(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "subscriptions": [],
            "liked_videos": [],
            "playlists": [],
            "watch_history": [],
            "search_history": [],
            "preferences": dict(self.DEFAULT_PREFS),
        }

    def load(self) -> None:
        with self._lock:
            state = self._empty_state()
            if self.path.is_file():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        for k in ("subscriptions", "liked_videos", "playlists", "watch_history", "search_history"):
                            if isinstance(raw.get(k), list):
                                state[k] = raw[k]
                        if isinstance(raw.get("preferences"), dict):
                            merged = dict(self.DEFAULT_PREFS)
                            merged.update(raw["preferences"])
                            state["preferences"] = merged
                except Exception as err:
                    logger.warning("Failed to load YouTube online profile: %s", err)
            self._data = state

    def save(self) -> None:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(tmp, self.path)
            except OSError as err:
                logger.warning("Failed to save YouTube online profile: %s", err)

    # --- Preferences ---
    def get_pref(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data["preferences"].get(key, self.DEFAULT_PREFS.get(key, default))

    def set_pref(self, key: str, value: Any) -> None:
        with self._lock:
            self._data["preferences"][key] = value
            self.save()

    # --- Subscriptions ---
    def list_subscriptions(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(s) for s in self._data["subscriptions"]]

    def is_subscribed(self, channel_id: str) -> bool:
        cid = str(channel_id or "").strip()
        if not cid:
            return False
        with self._lock:
            return any(str(s.get("channel_id") or "") == cid for s in self._data["subscriptions"])

    def toggle_subscription(self, channel_id: str, name: str, avatar_url: str = "") -> bool:
        cid = str(channel_id or "").strip()
        if not cid:
            return False
        with self._lock:
            subs = self._data["subscriptions"]
            for idx, s in enumerate(subs):
                if str(s.get("channel_id") or "") == cid:
                    subs.pop(idx)
                    self.save()
                    return False
            subs.insert(0, {
                "channel_id": cid,
                "name": str(name or cid).strip(),
                "avatar_url": str(avatar_url or "").strip(),
                "subscribed_at": int(time.time()),
            })
            self.save()
            return True

    def import_subscriptions_csv(self, csv_path: Path | str) -> int:
        """Import Google Takeout YouTube subscriptions.csv (Channel Id, Channel Url, Channel Title)."""
        import csv
        added = 0
        p = Path(csv_path)
        if not p.is_file():
            return 0
        with p.open("r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)
            rows = list(reader)
        with self._lock:
            existing = {str(s.get("channel_id") or "") for s in self._data["subscriptions"]}
            for row in rows:
                if len(row) < 3:
                    continue
                cid = row[0].strip()
                title = row[2].strip()
                if not cid or cid.lower().startswith("channel") or not cid.startswith("UC"):
                    continue
                if cid in existing:
                    continue
                existing.add(cid)
                self._data["subscriptions"].append({
                    "channel_id": cid,
                    "name": title or cid,
                    "avatar_url": "",
                    "subscribed_at": int(time.time()),
                })
                added += 1
            if added:
                self.save()
        return added

    # --- Liked Videos ---
    def list_liked(self) -> list[OnlineVideoItem]:
        with self._lock:
            return [OnlineVideoItem.from_dict(d) for d in self._data["liked_videos"]]

    def is_liked(self, video_id: str) -> bool:
        vid = str(video_id or "").strip()
        if not vid:
            return False
        with self._lock:
            return any(str(v.get("video_id") or "") == vid for v in self._data["liked_videos"])

    def toggle_like(self, item: OnlineVideoItem) -> bool:
        vid = str(item.video_id or "").strip()
        if not vid:
            return False
        with self._lock:
            liked = self._data["liked_videos"]
            for idx, v in enumerate(liked):
                if str(v.get("video_id") or "") == vid:
                    liked.pop(idx)
                    self.save()
                    return False
            liked.insert(0, item.to_dict())
            del liked[500:]
            self.save()
            return True

    # --- Online Playlists (Custom + Synced YouTube Playlists) ---
    def list_playlists(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(p) for p in self._data["playlists"]]

    def create_playlist(self, name: str, *, source_url: str = "", playlist_id: str = "", items: list[OnlineVideoItem] | None = None) -> dict[str, Any]:
        clean = str(name or "").strip() or "Playlist Online"
        pid = str(playlist_id or f"local_{int(time.time() * 1000)}")
        with self._lock:
            for existing in self._data["playlists"]:
                if existing.get("id") == pid:
                    existing["name"] = clean
                    if source_url:
                        existing["source_url"] = source_url
                    if items is not None:
                        existing["items"] = [it.to_dict() for it in items]
                    existing["updated_at"] = int(time.time())
                    self.save()
                    return dict(existing)
            entry = {
                "id": pid,
                "name": clean,
                "source_url": str(source_url or "").strip(),
                "is_synced_yt": bool(source_url),
                "items": [it.to_dict() for it in (items or [])],
                "created_at": int(time.time()),
                "updated_at": int(time.time()),
            }
            self._data["playlists"].insert(0, entry)
            self.save()
            return dict(entry)

    def add_item_to_playlist(self, playlist_id: str, item: OnlineVideoItem) -> bool:
        if not item.video_id:
            return False
        with self._lock:
            for pl in self._data["playlists"]:
                if pl.get("id") == playlist_id:
                    items = pl.setdefault("items", [])
                    if any(str(x.get("video_id") or "") == item.video_id for x in items):
                        return False
                    items.append(item.to_dict())
                    pl["updated_at"] = int(time.time())
                    self.save()
                    return True
        return False

    def delete_playlist(self, playlist_id: str) -> bool:
        with self._lock:
            before = len(self._data["playlists"])
            self._data["playlists"] = [p for p in self._data["playlists"] if p.get("id") != playlist_id]
            changed = len(self._data["playlists"]) != before
            if changed:
                self.save()
            return changed

    # --- Watch History & Search History ---
    def record_watch(self, item: OnlineVideoItem, position_sec: float = 0.0) -> None:
        if not item.video_id:
            return
        with self._lock:
            hist = self._data["watch_history"]
            hist[:] = [h for h in hist if str(h.get("video_id") or "") != item.video_id]
            entry = item.to_dict()
            entry["watched_at"] = int(time.time())
            entry["position_sec"] = max(0.0, float(position_sec or 0.0))
            hist.insert(0, entry)
            del hist[200:]
            self.save()

    def list_watch_history(self) -> list[OnlineVideoItem]:
        with self._lock:
            return [OnlineVideoItem.from_dict(d) for d in self._data["watch_history"]]

    def clear_watch_history(self) -> None:
        with self._lock:
            self._data["watch_history"] = []
            self.save()

    def record_search(self, query: str) -> None:
        q = str(query or "").strip()
        if not q:
            return
        with self._lock:
            sh = self._data["search_history"]
            sh[:] = [s for s in sh if str(s).lower() != q.lower()]
            sh.insert(0, q)
            del sh[30:]
            self.save()

    def list_search_history(self) -> list[str]:
        with self._lock:
            return list(self._data["search_history"])


# =====================================================================
# YOUTUBE ONLINE CLIENT (INNERTUBE + PORTABLE YT-DLP.EXE)
# =====================================================================

class YouTubeOnlineClient:
    """Resilient, paced, read-only YouTube client powered by InnerTube + bundled yt-dlp.exe."""

    _MIN_PACE_SEC = 0.22
    _FEED_CACHE_TTL_SEC = 300.0
    _STREAM_CACHE_TTL_SEC = 2400.0

    def __init__(self, profile_store: YouTubeOnlineProfileStore | None = None):
        self.profile = profile_store
        self._session = None
        self._session_lock = threading.Lock()
        self._pace_lock = threading.Lock()
        self._last_req_mono = 0.0
        self._cache_lock = threading.Lock()
        self._feed_cache: dict[str, tuple[float, Any]] = {}
        self._stream_cache: dict[str, ResolvedStream] = {}

    def _get_session(self):
        if self._session is None:
            with self._session_lock:
                if self._session is None:
                    import requests
                    sess = requests.Session()
                    sess.headers.update({
                        "User-Agent": _USER_AGENT,
                        "Origin": "https://www.youtube.com",
                        "Referer": "https://www.youtube.com/",
                        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                    })
                    self._session = sess
        return self._session

    def _pace(self) -> None:
        with self._pace_lock:
            now = time.monotonic()
            wait = self._MIN_PACE_SEC - (now - self._last_req_mono)
            if wait > 0:
                time.sleep(wait)
            self._last_req_mono = time.monotonic()

    @staticmethod
    def _context(lang: str = "vi") -> dict[str, Any]:
        is_en = str(lang or "vi").lower().startswith("en")
        return {
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": _INNERTUBE_CLIENT_VERSION,
                    "hl": "en" if is_en else "vi",
                    "gl": "US" if is_en else "VN",
                }
            }
        }

    def _innertube_post(self, endpoint: str, body: dict[str, Any], *, timeout: float = 12.0) -> dict[str, Any]:
        self._pace()
        resp = self._get_session().post(
            f"{_INNERTUBE_BASE}/{endpoint}?prettyPrint=false",
            json=body,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}

    def _cache_get(self, key: str, ttl: float = _FEED_CACHE_TTL_SEC) -> Any:
        with self._cache_lock:
            hit = self._feed_cache.get(key)
            if hit is not None and (time.monotonic() - hit[0]) < ttl:
                return hit[1]
        return None

    def _cache_set(self, key: str, val: Any) -> None:
        with self._cache_lock:
            if len(self._feed_cache) > 64:
                oldest = sorted(self._feed_cache.items(), key=lambda kv: kv[1][0])[:16]
                for k, _ in oldest:
                    self._feed_cache.pop(k, None)
            self._feed_cache[key] = (time.monotonic(), val)

    # --- 1. Live Autocomplete Suggestions ---
    def fetch_suggestions(self, query: str, *, lang: str = "vi") -> list[str]:
        q = str(query or "").strip()
        if not q:
            return []
        try:
            resp = self._get_session().get(
                _SUGGEST_URL,
                params={"client": "youtube", "ds": "yt", "hl": "en" if lang == "en" else "vi", "q": q},
                timeout=4.0,
            )
            resp.raise_for_status()
            txt = resp.text.strip()
            start = txt.find("(")
            end = txt.rfind(")")
            if start < 0 or end <= start:
                return []
            arr = json.loads(txt[start + 1 : end])
            if isinstance(arr, list) and len(arr) >= 2 and isinstance(arr[1], list):
                out: list[str] = []
                for entry in arr[1]:
                    if isinstance(entry, list) and entry and isinstance(entry[0], str):
                        val = entry[0].strip()
                        if val and val not in out:
                            out.append(val)
                return out[:10]
        except Exception:
            return []
        return []

    # --- 2. Search (Videos / Music / Playlists / Channels / Live) ---
    def search(self, query: str, *, filter_key: str = "all", lang: str = "vi", limit: int = 32) -> list[OnlineVideoItem]:
        q = str(query or "").strip()
        if not q:
            return []
        cache_key = f"search:{lang}:{filter_key}:{q.lower()}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return list(cached)
        body = {**self._context(lang), "query": q}
        params = SEARCH_FILTER_PARAMS.get(filter_key, "")
        if params:
            body["params"] = urllib.parse.unquote(params)
        data = self._innertube_post("search", body)
        items = _extract_items_from_payload(
            data,
            limit=limit,
            include_playlists=(filter_key in ("all", "playlists")),
            include_channels=(filter_key in ("all", "channels")),
        )
        self._cache_set(cache_key, items)
        return items

    # --- 3. Home / Topic Discovery Feed ---
    def fetch_home_feed(self, topic_key: str = "all", *, lang: str = "vi", force_refresh: bool = False) -> list[OnlineVideoItem]:
        key = str(topic_key or "all").strip().lower()
        cache_key = f"home:{lang}:{key}"
        if not force_refresh:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return list(cached)

        items: list[OnlineVideoItem] = []
        seen_ids: set[str] = set()

        def _append_unique(batch: list[OnlineVideoItem]) -> None:
            for it in batch:
                dk = f"{it.item_type}:{it.video_id or it.playlist_id or it.channel_id}"
                if dk not in seen_ids:
                    seen_ids.add(dk)
                    items.append(it)

        if key == "music":
            try:
                data = self._innertube_post("browse", {**self._context(lang), "browseId": _MUSIC_HUB_CHANNEL_ID})
                _append_unique(_extract_items_from_payload(data, limit=28, include_playlists=True, include_channels=False))
            except Exception as err:
                logger.debug("Music hub browse failed: %s", err)
            if len(items) < 12:
                _append_unique(self.search("official music video 2026" if lang == "en" else "nhạc trẻ mới hay nhất official mv", filter_key="videos", lang=lang, limit=24))
        elif key == "all":
            # Blend user's local online profile recommendations + fresh Music/Discovery feed!
            if self.profile is not None:
                hist = self.profile.list_watch_history()
                if hist:
                    try:
                        seed = hist[0]
                        watch = self.fetch_watch_info(seed.video_id, lang=lang)
                        _append_unique(watch.related[:12])
                    except Exception:
                        pass
                subs = self.profile.list_subscriptions()
                for sub in subs[:2]:
                    try:
                        ch = self.fetch_channel(sub["channel_id"], tab="videos", lang=lang, limit=6)
                        _append_unique(ch.items[:4])
                    except Exception:
                        pass
            # Supplement with fresh trending music/videos
            try:
                seed_q = "top trending music videos official" if lang == "en" else "nhạc trẻ thịnh hành official mv"
                _append_unique(self.search(seed_q, filter_key="videos", lang=lang, limit=24))
            except Exception:
                pass
            if len(items) < 16:
                try:
                    data = self._innertube_post("browse", {**self._context(lang), "browseId": _MUSIC_HUB_CHANNEL_ID})
                    _append_unique(_extract_items_from_payload(data, limit=20, include_playlists=True, include_channels=False))
                except Exception:
                    pass
        else:
            chip_query = next((q for k, _vi, _en, q in TOPIC_CHIPS if k == key), "")
            if chip_query:
                flt = "live" if key == "live" else ("all" if key == "mixes" else "videos")
                _append_unique(self.search(chip_query, filter_key=flt, lang=lang, limit=30))

        self._cache_set(cache_key, items)
        return items

    # --- 4. Watch Details + Related + Auto-Mix Radio + Comment Token ---
    def fetch_watch_info(self, video_id: str, *, playlist_id: str = "", lang: str = "vi") -> OnlineWatchInfo:
        vid = str(video_id or "").strip()
        if not _RE_VIDEO_ID.match(vid):
            return OnlineWatchInfo(video_id=vid)
        cache_key = f"watch:{lang}:{vid}:{playlist_id}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        body: dict[str, Any] = {**self._context(lang), "videoId": vid}
        if playlist_id:
            body["playlistId"] = playlist_id
        data = self._innertube_post("next", body)

        info = OnlineWatchInfo(video_id=vid)
        prim_nodes: list[tuple[str, dict[str, Any]]] = []
        _walk_nodes(data, {"videoPrimaryInfoRenderer", "videoSecondaryInfoRenderer"}, prim_nodes, limit=4)
        for kind, node in prim_nodes:
            if kind == "videoPrimaryInfoRenderer":
                info.title = _extract_text(node.get("title")).strip()
                vc = node.get("viewCount", {}).get("videoViewCountRenderer", {})
                info.views_text = _extract_text(vc.get("viewCount")) or _extract_text(vc.get("shortViewCount"))
                info.is_live = bool(vc.get("isLive", False))
                info.published_text = _extract_text(node.get("dateText")) or _extract_text(node.get("relativeDateText"))
                # Like count from segmented button
                like_nodes: list[tuple[str, dict[str, Any]]] = []
                _walk_nodes(node, {"likeButtonViewModel", "toggleButtonRenderer"}, like_nodes, limit=3)
                for _lk, lnode in like_nodes:
                    txt = _extract_text(
                        lnode.get("toggleButtonViewModel", {})
                        .get("toggleButtonViewModel", {})
                        .get("defaultButtonViewModel", {})
                        .get("buttonViewModel", {})
                        .get("title")
                    ) or _extract_text(lnode.get("defaultText"))
                    if txt:
                        info.likes_text = txt.strip()
                        break
            elif kind == "videoSecondaryInfoRenderer":
                owner = node.get("owner", {}).get("videoOwnerRenderer", {})
                info.channel_name = _extract_text(owner.get("title")).strip()
                info.channel_avatar = _best_thumb_url(owner.get("thumbnail"))
                info.subscriber_text = _extract_text(owner.get("subscriberCountText")).strip()
                info.channel_id = str(
                    owner.get("navigationEndpoint", {})
                    .get("browseEndpoint", {})
                    .get("browseId", "")
                ).strip()
                desc = _extract_text(node.get("attributedDescription")) or _extract_text(node.get("description"))
                info.description = desc.strip()

        info.chapters = parse_chapters_from_description(info.description)

        # Related videos from secondaryResults
        sec_results = (
            data.get("contents", {})
            .get("twoColumnWatchNextResults", {})
            .get("secondaryResults", {})
            .get("secondaryResults", {})
        )
        info.related = _extract_items_from_payload(sec_results, limit=25, include_playlists=True, include_channels=False)

        # Playlist / Mix panel if present
        pl_panel = (
            data.get("contents", {})
            .get("twoColumnWatchNextResults", {})
            .get("playlist", {})
            .get("playlist", {})
        )
        if isinstance(pl_panel, dict) and pl_panel.get("contents"):
            pp_nodes: list[tuple[str, dict[str, Any]]] = []
            _walk_nodes(pl_panel, {"playlistPanelVideoRenderer"}, pp_nodes, limit=50)
            for _k, pn in pp_nodes:
                item = _parse_playlist_panel_video(pn)
                if item is not None:
                    info.mix_items.append(item)

        # Comments continuation token
        for panel in data.get("engagementPanels") or []:
            if not isinstance(panel, dict):
                continue
            p_renderer = panel.get("engagementPanelSectionListRenderer", {})
            target_id = str(p_renderer.get("targetId") or "")
            if (
                target_id == "engagement-panel-comments-section"
                or p_renderer.get("panelIdentifier") == "comment-item-section"
                or "comment-item-section" in json.dumps(p_renderer)
            ):
                conts: list[tuple[str, dict[str, Any]]] = []
                _walk_nodes(p_renderer, {"continuationCommand"}, conts, limit=2)
                if conts and conts[0][1].get("token"):
                    info.comment_token = str(conts[0][1]["token"])
                    break

        self._cache_set(cache_key, info)
        return info

    def fetch_auto_mix(self, video_id: str, *, lang: str = "vi") -> list[OnlineVideoItem]:
        """Fetch YouTube Radio Mix (RD<videoId>) for infinite related auto-play."""
        vid = str(video_id or "").strip()
        if not _RE_VIDEO_ID.match(vid):
            return []
        try:
            info = self.fetch_watch_info(vid, playlist_id=f"RD{vid}", lang=lang)
            if info.mix_items:
                return info.mix_items
            return [x for x in info.related if x.item_type == "video"]
        except Exception:
            return []

    # --- 5. Lazy Comments Loader ---
    def fetch_comments(self, comment_token: str, *, lang: str = "vi", limit: int = 25) -> list[OnlineComment]:
        tok = str(comment_token or "").strip()
        if not tok:
            return []
        cache_key = f"comments:{lang}:{tok[:48]}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return list(cached)

        data = self._innertube_post("next", {**self._context(lang), "continuation": tok})
        nodes: list[tuple[str, dict[str, Any]]] = []
        _walk_nodes(data, {"commentEntityPayload", "commentRenderer"}, nodes, limit=limit * 2)
        comments: list[OnlineComment] = []
        seen: set[str] = set()
        for kind, node in nodes:
            if kind == "commentEntityPayload":
                props = node.get("properties") or {}
                author = node.get("author") or {}
                toolbar = node.get("toolbar") or {}
                cid = str(props.get("commentId") or node.get("key") or "")
                text = _extract_text(props.get("content")).strip()
                if not text or cid in seen:
                    continue
                seen.add(cid)
                comments.append(OnlineComment(
                    comment_id=cid,
                    author=str(author.get("displayName") or "").strip() or "YouTube User",
                    author_channel_id=str(author.get("channelId") or "").strip(),
                    avatar_url=str(author.get("avatarThumbnailUrl") or "").strip(),
                    text=text,
                    published_text=str(props.get("publishedTime") or "").strip(),
                    likes_text=str(toolbar.get("likeCountNotliked") or "").strip(),
                    replies_text=str(toolbar.get("replyCount") or "").strip(),
                    is_creator=bool(author.get("isCreator", False)),
                ))
            else:
                cid = str(node.get("commentId") or "")
                text = _extract_text(node.get("contentText")).strip()
                if not text or cid in seen:
                    continue
                seen.add(cid)
                comments.append(OnlineComment(
                    comment_id=cid,
                    author=_extract_text(node.get("authorText")).strip() or "YouTube User",
                    avatar_url=_best_thumb_url(node.get("authorThumbnail")),
                    text=text,
                    published_text=_extract_text(node.get("publishedTimeText")).strip(),
                    likes_text=_extract_text(node.get("voteCount")).strip(),
                    is_creator=bool(node.get("authorIsChannelOwner", False)),
                ))
            if len(comments) >= limit:
                break
        self._cache_set(cache_key, comments)
        return comments

    # --- 6. Channel View ---
    def fetch_channel(self, channel_id: str, *, tab: str = "videos", lang: str = "vi", limit: int = 30) -> OnlineChannelInfo:
        cid = str(channel_id or "").strip()
        if not cid:
            return OnlineChannelInfo(channel_id="", name="")
        cache_key = f"channel:{lang}:{cid}:{tab}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        tab_params = {
            "videos": "EgZ2aWRlb3PyBgQKAjoA",
            "popular": "EgZ2aWRlb3PyBgQKAjoA",
            "playlists": "EglwbGF5bGlzdHPyBgQKAkIA",
        }.get(tab, "EgZ2aWRlb3PyBgQKAjoA")

        body: dict[str, Any] = {**self._context(lang), "browseId": cid, "params": tab_params}
        data = self._innertube_post("browse", body)

        meta = data.get("metadata", {}).get("channelMetadataRenderer", {})
        name = str(meta.get("title") or "").strip()
        desc = str(meta.get("description") or "").strip()
        avatar = _best_thumb_url(meta.get("avatar"))
        vanity = str(meta.get("vanityChannelUrl") or "").strip()
        handle = vanity.rsplit("/", 1)[-1] if "/@" in vanity else ""

        # Extract subscriber count from header if present
        subs = ""
        header_nodes: list[tuple[str, dict[str, Any]]] = []
        _walk_nodes(data.get("header") or {}, {"c4TabbedHeaderRenderer", "pageHeaderViewModel"}, header_nodes, limit=2)
        for hkind, hnode in header_nodes:
            if hkind == "c4TabbedHeaderRenderer":
                subs = _extract_text(hnode.get("subscriberCountText")).strip()
                if not name:
                    name = str(hnode.get("title") or "").strip()
                if not avatar:
                    avatar = _best_thumb_url(hnode.get("avatar"))
            elif hkind == "pageHeaderViewModel":
                if not name:
                    name = _extract_text(hnode.get("title", {}).get("dynamicTextViewModel", {}).get("text")).strip()
                mrows = hnode.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows") or []
                for mr in mrows:
                    for mp in mr.get("metadataParts") or []:
                        t = _extract_text(mp.get("text")).strip()
                        if t.startswith("@") and not handle:
                            handle = t
                        elif any(tok in t.lower() for tok in ("sub", "đăng ký")) and not subs:
                            subs = t

        items = _extract_items_from_payload(
            data,
            limit=limit,
            include_playlists=(tab == "playlists"),
            include_channels=False,
        )
        for it in items:
            if not it.channel_name and name:
                it.channel_name = name
            if not it.channel_id:
                it.channel_id = cid
            if not it.channel_avatar and avatar:
                it.channel_avatar = avatar

        result = OnlineChannelInfo(
            channel_id=cid,
            name=name or cid,
            handle=handle,
            avatar_url=avatar,
            subscriber_text=subs,
            description=desc,
            items=items,
        )
        self._cache_set(cache_key, result)
        return result

    # --- 7. Playlist Fetch via Portable yt-dlp.exe (--flat-playlist, 1 request!) ---
    def _cookie_args(self, cookies_browser: str = "", cookies_file: str = "") -> list[str]:
        c_file = str(cookies_file or "").strip()
        if c_file and Path(c_file).is_file():
            return ["--cookies", c_file]
        browser = normalize_cookies_browser(cookies_browser)
        if browser:
            return ["--cookies-from-browser", browser]
        return []

    def fetch_playlist(
        self,
        playlist_url_or_id: str,
        *,
        cookies_browser: str = "",
        cookies_file: str = "",
        processes: OwnedProcesses | None = None,
        max_items: int = 150,
    ) -> tuple[str, list[OnlineVideoItem]]:
        raw = str(playlist_url_or_id or "").strip()
        if not raw:
            return ("", [])
        if raw.startswith(("http://", "https://", ":")):
            target = raw
        else:
            target = f"https://www.youtube.com/playlist?list={raw}"

        ytdlp = resolve_ytdlp_executable()
        if not ytdlp.is_file():
            raise FileNotFoundError(f"Không tìm thấy yt-dlp.exe tại {ytdlp}")

        cmd = [
            str(ytdlp),
            "--flat-playlist",
            "--no-warnings",
            "--skip-download",
            "--playlist-end",
            str(max(1, int(max_items))),
            "-J",
            *self._cookie_args(cookies_browser, cookies_file),
            "--",
            target,
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
        )
        if processes is not None:
            processes.track(proc)
        try:
            stdout, stderr = proc.communicate(timeout=35)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise TimeoutError("Hết thời gian tải danh sách phát YouTube.")
        finally:
            if processes is not None:
                processes.release(proc)

        if proc.returncode != 0 or not stdout.strip():
            msg = (stderr or "").strip().splitlines()
            tail = msg[-1] if msg else f"yt-dlp exit {proc.returncode}"
            raise RuntimeError(tail)

        data = json.loads(stdout)
        title = str(data.get("title") or "YouTube Playlist").strip()
        pl_id = str(data.get("id") or "").strip()
        entries = data.get("entries") or []
        items: list[OnlineVideoItem] = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            vid = str(e.get("id") or "").strip()
            if not _RE_VIDEO_ID.match(vid):
                continue
            dur_s = int(e.get("duration") or 0)
            items.append(OnlineVideoItem(
                video_id=vid,
                title=str(e.get("title") or vid).strip(),
                channel_name=str(e.get("channel") or e.get("uploader") or "").strip(),
                channel_id=str(e.get("channel_id") or "").strip(),
                thumbnail_url=_best_thumb_url(e.get("thumbnails"), vid),
                duration_text=format_seconds_mmss(dur_s) if dur_s > 0 else "",
                duration_sec=dur_s,
                playlist_id=pl_id,
                item_type="video",
            ))
        return title, items

    # --- 8. Direct Stream + Subtitles Resolver via Portable yt-dlp.exe ---
    def resolve_stream(
        self,
        video_id: str,
        *,
        cookies_browser: str = "",
        cookies_file: str = "",
        processes: OwnedProcesses | None = None,
        force_refresh: bool = False,
    ) -> ResolvedStream:
        vid = str(video_id or "").strip()
        if not _RE_VIDEO_ID.match(vid):
            raise ValueError(f"Video ID không hợp lệ: {vid}")

        if not force_refresh:
            with self._cache_lock:
                cached = self._stream_cache.get(vid)
                if cached is not None and (time.monotonic() - cached.resolved_at_mono) < self._STREAM_CACHE_TTL_SEC:
                    return cached

        ytdlp = resolve_ytdlp_executable()
        if not ytdlp.is_file():
            raise FileNotFoundError(f"Không tìm thấy yt-dlp.exe tại {ytdlp}")

        url = f"https://www.youtube.com/watch?v={vid}"
        cmd = [
            str(ytdlp),
            "--no-playlist",
            "--no-warnings",
            "--skip-download",
            "-J",
            *self._cookie_args(cookies_browser, cookies_file),
            "--",
            url,
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
        )
        if processes is not None:
            processes.track(proc)
        try:
            stdout, stderr = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise TimeoutError("Hết thời gian kết nối luồng YouTube.")
        finally:
            if processes is not None:
                processes.release(proc)

        if proc.returncode != 0 or not stdout.strip():
            msg = (stderr or "").strip().splitlines()
            tail = msg[-1] if msg else f"yt-dlp exit {proc.returncode}"
            raise RuntimeError(tail)

        info = json.loads(stdout)
        resolved = self._build_resolved_stream(vid, info)
        with self._cache_lock:
            if len(self._stream_cache) > 40:
                oldest = sorted(self._stream_cache.items(), key=lambda kv: kv[1].resolved_at_mono)[:10]
                for k, _ in oldest:
                    self._stream_cache.pop(k, None)
            self._stream_cache[vid] = resolved
        return resolved

    @staticmethod
    def _build_resolved_stream(vid: str, info: dict[str, Any]) -> ResolvedStream:
        formats = info.get("formats") or []
        audio_only: list[dict[str, Any]] = []
        video_only: list[dict[str, Any]] = []
        progressive: list[dict[str, Any]] = []

        for f in formats:
            if not isinstance(f, dict):
                continue
            f_url = str(f.get("url") or "").strip()
            if not f_url or f.get("protocol") in ("mhtml", "storyboard"):
                continue
            ac = str(f.get("acodec") or "none")
            vc = str(f.get("vcodec") or "none")
            has_a = ac not in ("none", "")
            has_v = vc not in ("none", "")
            if has_a and not has_v:
                audio_only.append(f)
            elif has_v and not has_a:
                video_only.append(f)
            elif has_v and has_a:
                progressive.append(f)

        # Pick best Hi-Fi Audio stream (prefer Opus 48kHz highest bitrate, then AAC M4A)
        def _audio_rank(f: dict[str, Any]) -> tuple[int, int, float, int]:
            ac = str(f.get("acodec") or "").lower()
            proto = str(f.get("protocol") or "").lower()
            is_https = 1 if proto in ("https", "http") else 0
            is_opus = 2 if "opus" in ac else (1 if ("mp4a" in ac or "aac" in ac) else 0)
            abr = float(f.get("abr") or f.get("tbr") or 0.0)
            asr = int(f.get("asr") or 0)
            return (is_https, is_opus, abr, asr)

        best_audio = max(audio_only, key=_audio_rank) if audio_only else (
            max(progressive, key=lambda f: float(f.get("abr") or f.get("tbr") or 0.0)) if progressive else None
        )

        # Best progressive fallback (e.g. 720p/360p MP4 with muxed audio)
        best_prog = None
        if progressive:
            best_prog = max(
                progressive,
                key=lambda f: (
                    1 if str(f.get("protocol") or "").lower() in ("https", "http") else 0,
                    int(f.get("height") or 0),
                    float(f.get("tbr") or 0.0),
                ),
            )

        # Bucket video streams by standard YouTube resolutions, supporting both 16:9 AND
        # CinemaScope 21:9 MVs (e.g., 1920x776 -> 1080p, 3840x1550 -> 2160p) and vertical Shorts.
        buckets: dict[str, dict[str, Any]] = {}
        target_heights = (2160, 1440, 1080, 720, 480, 360)
        all_video = video_only + progressive

        def _effective_resolution(f: dict[str, Any]) -> int:
            w = int(f.get("width") or 0)
            h = int(f.get("height") or 0)
            if w <= 0 and h <= 0:
                return 0
            if w >= h:
                return max(h, int(round(w * 9.0 / 16.0)))
            return min(w, h) if w > 0 else h

        def _video_rank(f: dict[str, Any]) -> tuple[int, int, float, float]:
            vc = str(f.get("vcodec") or "").lower()
            ext = str(f.get("ext") or "").lower()
            proto = str(f.get("protocol") or "").lower()
            is_https = 1 if proto in ("https", "http") else 0
            # H.264 in MP4 decodes natively on 100% of Windows GPUs via QtMultimedia WMF/FFmpeg!
            codec_score = 3 if ("avc" in vc or "h264" in vc) and ext == "mp4" else (
                2 if "vp9" in vc else (1 if "av01" in vc else 0)
            )
            fps = float(f.get("fps") or 30.0)
            tbr = float(f.get("vbr") or f.get("tbr") or 0.0)
            return (is_https, codec_score, fps, tbr)

        for target_h in target_heights:
            tol = max(50, int(target_h * 0.12))
            cands = [
                f for f in all_video
                if abs(_effective_resolution(f) - target_h) <= tol
                and str(f.get("protocol") or "").lower() in ("https", "http", "m3u8_native", "m3u8")
            ]
            if not cands:
                continue
            pick = max(cands, key=_video_rank)
            label = f"{target_h}p"
            buckets[label] = {
                "url": str(pick.get("url") or ""),
                "height": int(pick.get("height") or target_h),
                "width": int(pick.get("width") or 0),
                "fps": int(round(float(pick.get("fps") or 30))),
                "vcodec": str(pick.get("vcodec") or ""),
                "ext": str(pick.get("ext") or ""),
                "progressive": str(pick.get("acodec") or "none") not in ("none", ""),
                "headers": dict(pick.get("http_headers") or {}),
            }

        # Chapters
        chapters: list[OnlineChapter] = []
        raw_ch = info.get("chapters") or []
        for ch in raw_ch:
            if isinstance(ch, dict):
                chapters.append(OnlineChapter(
                    title=str(ch.get("title") or "").strip(),
                    start_sec=float(ch.get("start_time") or 0.0),
                    end_sec=float(ch.get("end_time") or 0.0),
                ))
        if not chapters and info.get("description"):
            chapters = parse_chapters_from_description(str(info.get("description")), float(info.get("duration") or 0.0))

        # Subtitles (prefer human subtitles, then curated auto-captions)
        sub_tracks: list[OnlineSubtitleTrack] = []
        priority_langs = ("vi", "en", "en-US", "en-GB", "ja", "ko", "zh-Hans", "zh-Hant", "zh", "fr", "de", "es")

        def _collect_subs(sub_dict: dict[str, Any], is_auto: bool) -> None:
            if not isinstance(sub_dict, dict):
                return
            ordered_keys = [k for k in priority_langs if k in sub_dict] + [
                k for k in sub_dict.keys() if k not in priority_langs
            ]
            seen_codes = {t.lang_code for t in sub_tracks}
            for lang_code in ordered_keys:
                if is_auto and lang_code not in priority_langs and len(sub_tracks) >= 16:
                    continue
                if lang_code in seen_codes:
                    continue
                entries = sub_dict.get(lang_code)
                if not isinstance(entries, list):
                    continue
                chosen = None
                for pref_ext in ("json3", "vtt", "srv3"):
                    chosen = next((e for e in entries if isinstance(e, dict) and e.get("ext") == pref_ext and e.get("url")), None)
                    if chosen:
                        break
                if chosen:
                    name = str(chosen.get("name") or lang_code).strip()
                    if is_auto and "auto" not in name.lower() and "tự động" not in name.lower():
                        name = f"{name} (Auto)"
                    sub_tracks.append(OnlineSubtitleTrack(
                        lang_code=str(lang_code),
                        label=name,
                        url=str(chosen["url"]),
                        ext=str(chosen.get("ext") or "vtt"),
                        is_auto=is_auto,
                    ))
                    seen_codes.add(lang_code)

        _collect_subs(info.get("subtitles") or {}, is_auto=False)
        _collect_subs(info.get("automatic_captions") or {}, is_auto=True)

        headers = dict((best_audio or best_prog or {}).get("http_headers") or info.get("http_headers") or {})
        if "User-Agent" not in headers:
            headers["User-Agent"] = _USER_AGENT

        return ResolvedStream(
            video_id=vid,
            title=str(info.get("title") or vid).strip(),
            channel_name=str(info.get("channel") or info.get("uploader") or "").strip(),
            channel_id=str(info.get("channel_id") or "").strip(),
            duration_sec=float(info.get("duration") or 0.0),
            thumbnail_url=str(info.get("thumbnail") or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"),
            audio_url=str((best_audio or {}).get("url") or (best_prog or {}).get("url") or info.get("url") or ""),
            audio_codec=str((best_audio or {}).get("acodec") or ""),
            audio_abr=float((best_audio or {}).get("abr") or (best_audio or {}).get("tbr") or 0.0),
            audio_sr=int((best_audio or {}).get("asr") or 48000),
            video_streams=buckets,
            progressive_url=str((best_prog or {}).get("url") or ""),
            http_headers=headers,
            chapters=chapters,
            subtitles=sub_tracks,
            resolved_at_mono=time.monotonic(),
            is_live=bool(info.get("is_live", False)),
        )

    # --- 9. Fetch & Parse YouTube Subtitle/CC Track ---
    def fetch_subtitle_cues(self, track: OnlineSubtitleTrack) -> list[OnlineSubtitleCue]:
        if not track or not track.url:
            return []
        cache_key = f"sub:{track.lang_code}:{track.url[:100]}"
        cached = self._cache_get(cache_key, ttl=900.0)
        if cached is not None:
            return list(cached)
        resp = self._get_session().get(track.url, timeout=10.0)
        resp.raise_for_status()
        text = resp.text
        if track.ext == "json3" or text.lstrip().startswith("{"):
            cues = parse_json3_subtitles(text)
        else:
            cues = parse_vtt_subtitles(text)
        self._cache_set(cache_key, cues)
        return cues

    # --- 10. Verify Read-Only Browser / Cookie Account Connection ---
    def verify_cookie_connection(
        self,
        *,
        cookies_browser: str = "",
        cookies_file: str = "",
        processes: OwnedProcesses | None = None,
    ) -> tuple[bool, str, int]:
        """Test read-only cookie access to Liked Videos (:ytfav) and return (ok, message, count)."""
        if not cookies_browser and not (cookies_file and Path(cookies_file).is_file()):
            return (False, "Chưa chọn trình duyệt hoặc tệp cookies.txt.", 0)
        try:
            title, items = self.fetch_playlist(
                ":ytfav",
                cookies_browser=cookies_browser,
                cookies_file=cookies_file,
                processes=processes,
                max_items=5,
            )
            return (True, title or "Liked Videos", len(items))
        except Exception as err:
            raw = str(err)
            low = raw.lower()
            if "could not copy chrome cookie database" in low or "dpapi" in low or "permission" in low:
                return (
                    False,
                    "Trình duyệt Chrome/Edge đang khóa Cookie khi mở. Hãy chọn Firefox, tạm đóng trình duyệt 3 giây, hoặc dùng tệp cookies.txt.",
                    0,
                )
            return (False, raw[:220], 0)
