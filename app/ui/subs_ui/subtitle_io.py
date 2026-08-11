import re
import json
from typing import List

def _parse_srt_time(ts: str) -> float:
    # formats: HH:MM:SS,mmm or MM:SS,mmm
    ts = ts.strip().replace(',', '.')
    parts = ts.split(':')
    if len(parts) == 3:
        h = int(parts[0])
        m = int(parts[1])
        s = float(parts[2])
        return h * 3600 + m * 60 + s
    if len(parts) == 2:
        m = int(parts[0])
        s = float(parts[1])
        return m * 60 + s
    return float(ts)

def _format_srt_time(seconds: float) -> str:
    ms = int(round((seconds - int(seconds)) * 1000))
    s = int(seconds) % 60
    m = (int(seconds) // 60) % 60
    h = int(seconds) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def _parse_ass_time(ts: str) -> float:
    # ASS uses H:MM:SS.cc (centiseconds)
    ts = ts.strip()
    parts = ts.split(':')
    if len(parts) == 3:
        h = int(parts[0])
        m = int(parts[1])
        s = float(parts[2])
        return h * 3600 + m * 60 + s
    return float(ts)

def _format_ass_time(seconds: float) -> str:
    # H:MM:SS.cc (centiseconds)
    total_cs = int(round(seconds * 100))
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def parse_srt_text(text: str) -> List[dict]:
    items = re.split(r"\n\s*\n", text.strip())
    segments = []
    for item in items:
        lines = item.strip().splitlines()
        if not lines:
            continue
        # times usually on second line
        if len(lines) >= 2 and '-->' in lines[1]:
            times = lines[1]
            txt = '\n'.join(lines[2:]) if len(lines) > 2 else lines[-1]
        else:
            # try first line with times
            times = lines[0]
            txt = '\n'.join(lines[1:]) if len(lines) > 1 else ''
        m = re.search(r"([0-9:,\.\s]+)\s*-->\s*([0-9:,\.\s]+)", times)
        if not m:
            continue
        start = _parse_srt_time(m.group(1))
        end = _parse_srt_time(m.group(2))
        segments.append({'start': start, 'end': end, 'text': txt})
    return segments

def parse_ass_text(text: str) -> List[dict]:
    segments = []
    lines = text.splitlines()
    events_idx = None
    for i, l in enumerate(lines):
        if l.strip().lower().startswith('[events]'):
            events_idx = i
            break
    if events_idx is None:
        return segments
    # find format line
    fmt = None
    for l in lines[events_idx+1: events_idx+20]:
        if l.strip().lower().startswith('format:'):
            fmt = l.strip()[7:].strip()
            break
    # parse dialogue lines
    for l in lines[events_idx+1:]:
        if l.strip().lower().startswith('dialogue:'):
            # split only first 9 commas to keep text intact
            parts = l.split(',', 9)
            if len(parts) >= 10:
                start = _parse_ass_time(parts[1])
                end = _parse_ass_time(parts[2])
                txt = parts[9].strip()
                segments.append({'start': start, 'end': end, 'text': txt})
    return segments

def load_subs(path: str) -> List[dict]:
    lower = path.lower()
    if lower.endswith('.json'):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and 'segments' in data:
            return data['segments']
        if isinstance(data, list):
            return data
        return []
    if lower.endswith('.srt'):
        with open(path, 'r', encoding='utf-8') as f:
            return parse_srt_text(f.read())
    if lower.endswith('.ass'):
        with open(path, 'r', encoding='utf-8') as f:
            return parse_ass_text(f.read())
    # fallback try json
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and 'segments' in data:
            return data['segments']
    except Exception:
        pass
    return []

def save_subs(path: str, segments: List[dict]):
    lower = path.lower()
    if lower.endswith('.json'):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'segments': segments}, f, ensure_ascii=False, indent=2)
        return
    if lower.endswith('.srt'):
        with open(path, 'w', encoding='utf-8') as f:
            for i, s in enumerate(segments, start=1):
                start = _format_srt_time(float(s.get('start', 0.0)))
                end = _format_srt_time(float(s.get('end', 0.0)))
                txt = s.get('text', '')
                f.write(f"{i}\n{start} --> {end}\n{txt}\n\n")
        return
    if lower.endswith('.ass'):
        header = (
            "[Script Info]\n" 
            "ScriptType: v4.00+\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )
        with open(path, 'w', encoding='utf-8') as f:
            f.write(header)
            for s in segments:
                start = _format_ass_time(float(s.get('start', 0.0)))
                end = _format_ass_time(float(s.get('end', 0.0)))
                txt = s.get('text', '')
                f.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{txt}\n")
        return
    # default to json
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'segments': segments}, f, ensure_ascii=False, indent=2)
