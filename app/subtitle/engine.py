import copy
from subtitle.model import SubtitleLine

def add_translation(subs, lang, texts):
    for s, t in zip(subs, texts):
        s.bottom = SubtitleLine(lang=lang, text=t)

def switch_top_language(subs, lang, texts):
    for s, t in zip(subs, texts):
        s.top = SubtitleLine(lang=lang, text=t)

def clone_subs(subs):
    return copy.deepcopy(subs)
