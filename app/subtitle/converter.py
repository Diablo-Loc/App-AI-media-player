from subtitle.model import Subtitle, SubtitleLine

def refined_to_subtitles(refined_segments, lang="ja"):
    subs = []
    lang_clean = str(lang).lower().strip()

    # Xác định style phù hợp cho dòng Lời Gốc (top)
    if lang_clean == "en":
        top_style = "EN"
    elif lang_clean == "vi":
        top_style = "VI"
    else:
        top_style = "JP"  # Mặc định cho CJK (JA/ZH/KO)

    for seg in refined_segments:
        sub = Subtitle(start=seg["start"], end=seg["end"])
        orig_text = seg.get("text", "").strip()

        # Dòng Lời Gốc
        sub.top = SubtitleLine(
            text=orig_text,
            lang=lang_clean,
            style=top_style
        )

        # 🇺🇸 Nếu nguồn là Tiếng Anh: Khởi tạo sẵn Middle là Tiếng Anh
        if lang_clean == "en":
            sub.middle = SubtitleLine(
                text=orig_text,
                lang="en",
                style="EN"
            )
            sub.bottom = None

        # 🇻🇳 Nếu nguồn là Tiếng Việt: Khởi tạo sẵn Bottom là Tiếng Việt
        elif lang_clean == "vi":
            sub.middle = None
            sub.bottom = SubtitleLine(
                text=orig_text,
                lang="vi",
                style="VI"
            )

        # 🇯🇵 🇰🇷 🇨🇳 Ngôn ngữ khác (JA/ZH/KO): Chờ pipeline dịch điền middle & bottom
        else:
            sub.middle = None
            sub.bottom = None

        subs.append(sub)

    return subs