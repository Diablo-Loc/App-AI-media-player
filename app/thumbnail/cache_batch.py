"""Coalesce disposable thumbnail cache writes within one owned scan worker."""
import time


class ThumbnailCacheBatch:
    def __init__(self, library, count=20, seconds=2.0, clock=time.monotonic):
        self.library = library
        self.count, self.seconds, self.clock = count, seconds, clock
        self.dirty = 0
        self.last_flush = self.next_attempt = clock()

    def stage(self, media_id, path):
        if self.library.stage_thumbnail_in_db(media_id, path):
            self.dirty += 1
        now = self.clock()
        if now >= self.next_attempt and (self.dirty >= self.count or now-self.last_flush >= self.seconds):
            self.flush()

    def flush(self):
        if not self.dirty:
            return
        self.library.save()
        now = self.clock()
        if getattr(self.library, '_last_save_succeeded', True):
            self.dirty = 0
            self.last_flush = now
            self.next_attempt = now
        else:
            self.next_attempt = now + self.seconds
