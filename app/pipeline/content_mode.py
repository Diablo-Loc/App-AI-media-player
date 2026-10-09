"""Content selection for new AI jobs; old settings retain the lyric profile."""

LYRICS = "lyrics"
DIALOGUE = "dialogue"


def resolve_content_mode(value):
    return DIALOGUE if value == DIALOGUE else LYRICS
