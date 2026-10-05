"""Focused guards for playback work that must stay off the hot path."""
from collections import deque
import ctypes
from types import SimpleNamespace
import unittest

from ui.system_media_manager import SystemMediaManager


class _FakeArray:
    def __init__(self, counter):
        self.counter = counter

    def reshape(self, frames, channels):
        self.counter['shape'] = (frames, channels)
        return self

    def copy(self):
        self.counter['copies'] += 1
        return self


class _FakeNumpy:
    float32 = object()

    def __init__(self, counter):
        self.counter = counter

    def frombuffer(self, *_args, **_kwargs):
        self.counter['frombuffer'] += 1
        return _FakeArray(self.counter)


class NativePcmHotPathTests(unittest.TestCase):
    def test_pcm_copy_is_off_by_default_and_does_not_touch_buffer(self):
        owner = SimpleNamespace(
            _closing=False,
            _capture_audio=False,
            _numpy=None,
            _cb_count=0,
            _pending_audio=deque(maxlen=2),
            _schedule_pending_events=lambda: None,
        )
        # None is deliberately safe only when the hot path returns before any
        # pointer dereference.  This catches accidental reintroduction of work.
        SystemMediaManager._native_audio_callback(owner, None, 480, 2, 48000)
        self.assertEqual(owner._cb_count, 0)
        self.assertEqual(len(owner._pending_audio), 0)

    def test_explicit_pcm_capture_keeps_the_existing_bounded_copy_contract(self):
        counts = {'frombuffer': 0, 'copies': 0, 'shape': None, 'scheduled': 0}
        raw = (ctypes.c_float * 960)()
        pointer = ctypes.cast(raw, ctypes.POINTER(ctypes.c_float))
        owner = SimpleNamespace(
            _closing=False,
            _capture_audio=True,
            _numpy=_FakeNumpy(counts),
            _cb_count=0,
            _pending_audio=deque(maxlen=2),
            _schedule_pending_events=lambda: counts.__setitem__(
                'scheduled', counts['scheduled'] + 1
            ),
        )
        SystemMediaManager._native_audio_callback(owner, pointer, 480, 2, 48000)
        self.assertEqual(owner._cb_count, 1)
        self.assertEqual(counts['frombuffer'], 1)
        self.assertEqual(counts['copies'], 1)
        self.assertEqual(counts['shape'], (480, 2))
        self.assertEqual(counts['scheduled'], 1)
        self.assertEqual(len(owner._pending_audio), 1)


if __name__ == '__main__':
    unittest.main()
