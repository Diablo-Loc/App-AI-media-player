"""Subtitle export time formatting with unit rounding before clock rollover."""


def _clock(seconds, units):
    total = int(round(max(0.0, float(seconds)) * units))
    whole, fraction = divmod(total, units)
    hours, remaining = divmod(whole, 3600)
    minutes, seconds = divmod(remaining, 60)
    return hours, minutes, seconds, fraction


def srt_time(seconds):
    hours, minutes, seconds, milliseconds = _clock(seconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def lrc_time(seconds):
    hours, minutes, seconds, centiseconds = _clock(seconds, 100)
    return f"{hours * 60 + minutes:02}:{seconds:02}.{centiseconds:02}"


def ass_time(seconds):
    hours, minutes, seconds, centiseconds = _clock(seconds, 100)
    return f"{hours}:{minutes:02}:{seconds:02}.{centiseconds:02}"
