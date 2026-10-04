"""Viewport-sized Widgets pool. Search changes the view, never the play queue."""
from math import ceil
import time

from PySide6.QtCore import QObject, QEvent, QTimer, Qt
from PySide6.QtWidgets import QLabel

from .elided_label import ElidedLabel
from .icons import label_icon
from .playlist_loading_overlay import PlaylistLoadingOverlay


class PlaylistViewport(QObject):
    ROW_HEIGHT = 88
    PITCH = 93
    MARGIN = 10

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.rows = []
        self.indices = {}
        self.index_by_id = {}
        self.playback_order = []
        self.loading = PlaylistLoadingOverlay(page.playlist_scroll.viewport())
        self.generation = 0
        self.job = None
        self.is_busy = False
        self.preparing = False
        self.chunk_timer = QTimer(self)
        self.chunk_timer.setSingleShot(True)
        self.chunk_timer.timeout.connect(self._filter_chunk)
        self.ready_timer = QTimer(self)
        self.ready_timer.setSingleShot(True)
        self.ready_timer.timeout.connect(self._check_ready)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.render)
        page.playlist_items_layout.setEnabled(False)
        page.playlist_scroll.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Resize, QEvent.Show):
            self.loading.setGeometry(watched.rect())
            self.schedule()
        return False

    def schedule(self):
        if not self.timer.isActive():
            self.timer.start(16)

    def load(self, data):
        p = self.page
        p.master_data = list(data)
        p.original_data = list(p.master_data)
        self.playback_order = p.get_shuffled_list() if p.is_shuffle else list(p.master_data)
        self.filter()

    def set_order(self, order):
        self.playback_order = list(order)
        self.filter()

    def filter(self):
        # Synchronous compatibility for load/shuffle callers. Search uses the
        # cooperative path below and commits only a complete result.
        self._cancel_pending()
        self._finish_loading()
        p = self.page
        p.search_timer.stop()
        query = p.search_input.text().strip().lower()
        p.all_items_data = [item for item in self.playback_order
                            if not query or query in getattr(item, 'title', '').lower()
                            or query in getattr(item, 'artist', '').lower()]
        p.playlist_scroll.verticalScrollBar().setValue(0)
        self.refresh()

    def _cancel_pending(self):
        self.generation += 1
        self.job = None
        self.chunk_timer.stop()
        self.ready_timer.stop()

    def _begin_loading(self):
        self.is_busy = True
        self.preparing = True
        self.page.playlist_items_widget.setEnabled(False)
        self.page.search_input.setToolTip('')
        message = 'Đang tìm kiếm…' if self.page.search_input.text().strip() else 'Đang khôi phục danh sách…'
        self.loading.begin(message)
        for card in self.rows:
            thumb = card._playlist_thumb
            thumb.setProperty('playlist_visible', False)
            if thumb._current_worker and not thumb._current_worker._completed:
                thumb._current_worker.cancel()
                thumb._current_worker = None

    def _finish_loading(self):
        self.is_busy = False
        self.preparing = False
        self.loading.hide()
        self.page.playlist_items_widget.setEnabled(True)

    def request_filter(self, text):
        self.page.search_timer.stop()
        self._cancel_pending()
        self._begin_loading()
        self.page.search_timer.start(300 if text.strip() else 0)

    def filter_async(self):
        self.page.search_timer.stop()
        self._cancel_pending()
        self._begin_loading()
        self.job = dict(generation=self.generation, query=self.page.search_input.text().strip().lower(),
                        source=self.playback_order, offset=0, results=[], indices={})
        # Yield for the loading overlay to paint before any preparation.
        self.chunk_timer.start(16)

    def _filter_chunk(self):
        job = self.job
        if job is None or job['generation'] != self.generation:
            return
        end = min(job['offset'] + 500, len(job['source']))
        query = job['query']
        try:
            for i in range(job['offset'], end):
                item = job['source'][i]
                if (not query or query in getattr(item, 'title', '').lower()
                        or query in getattr(item, 'artist', '').lower()):
                    job['indices'][item.id] = len(job['results'])
                    job['results'].append(item)
        except (AttributeError, TypeError, RuntimeError):
            self._cancel_pending()
            self.page.search_input.setToolTip('Không thể lọc danh sách. Hãy thử lại.')
            self._finish_loading()
            self.render()
            return
        job['offset'] = end
        if end < len(job['source']):
            self.chunk_timer.start(1)
            return
        self.job = None
        self.preparing = False
        self.page.all_items_data = job['results']
        self.page.playlist_scroll.verticalScrollBar().setValue(0)
        self.refresh(job['indices'])
        self.loading.raise_()
        self.ready_deadline = time.monotonic() + 2
        self.ready_timer.start(16)

    def _check_ready(self):
        if not self.is_busy or self.preparing:
            return
        if self.timer.isActive():
            # Scrollbar/viewport reflow can arrive after commit; settle row
            # geometry under the overlay before exposing the completed view.
            self.timer.stop()
            self.render()
        ready = True
        for card in self.page.cards_map.values():
            thumb = card._playlist_thumb
            if thumb.property('playlist_visible') is not True:
                continue
            worker = thumb._current_worker
            if (not thumb._is_loaded and worker is not None
                    and not getattr(worker, '_gui_completed', False)):
                ready = False
                break
        if ready or time.monotonic() >= self.ready_deadline:
            self._finish_loading()
        else:
            self.ready_timer.start(16)

    def refresh(self, prepared_indices=None):
        p = self.page
        self.index_by_id = (prepared_indices if prepared_indices is not None else
                            {item.id: i for i, item in enumerate(p.all_items_data)})
        self.indices.clear()
        for card in self.rows:
            card.hide()
            thumb = card._playlist_thumb
            thumb.setProperty('playlist_visible', False)
            if thumb._current_worker:
                thumb._current_worker.cancel()
                thumb._current_worker = None
        count = len(p.all_items_data)
        p.playlist_items_widget.setMinimumHeight(max(0, count * self.PITCH - 5) + 20)
        self.render()
        self.update_counter()

    def update_counter(self):
        p = self.page
        index = self.index_by_id.get(p.current_playing_id, -1)
        p.update_playing_status(index + 1, len(p.all_items_data))

    def _new_card(self, index, item):
        p = self.page
        card = p.create_playlist_card(index + 1, item.title, getattr(item, 'artist', 'Unknown'), None, item)
        card.setParent(p.playlist_items_widget)
        # References avoid repeated child-tree searches during scrolling.
        card._playlist_index = card.findChildren(QLabel)[0]
        card._playlist_title, card._playlist_artist = card.findChildren(ElidedLabel)
        card._playlist_thumb = card.layout().itemAt(1).widget()
        self.rows.append(card)
        return card

    def _bind(self, card, index, item):
        p = self.page
        thumb = card._playlist_thumb
        previous_key = thumb.cache_key
        thumb.item_data = item
        thumb._build_cache_key()
        if getattr(card, '_bound_item', None) is not item or previous_key != thumb.cache_key:
            if thumb._current_worker:
                thumb._current_worker.cancel()
            thumb._current_worker = None
            thumb._is_loaded = False
            thumb.clear()
            label_icon(thumb, 'music', size=24)
            thumb.setStyleSheet('background-color: #222; border: none;')
            card._bound_item = item
        card._playlist_title.setText(item.title)
        card._playlist_artist.setText(getattr(item, 'artist', 'Unknown'))
        card._playlist_item = item
        card._playlist_index.setText(str(index + 1))
        largest = max(index + 1, len(p.all_items_data))
        card._playlist_index.setFixedWidth(max(14, card._playlist_index.fontMetrics().horizontalAdvance(str(largest)) + 2))
        if item.id == p.current_playing_id:
            p.set_card_active_style(card)
        else:
            p.set_card_normal_style(card)

    def render(self):
        if self.preparing:
            return
        p = self.page
        count = len(p.all_items_data)
        viewport = p.playlist_scroll.viewport()
        y = p.playlist_scroll.verticalScrollBar().value()
        first = max(0, (y - self.MARGIN) // self.PITCH - 1)
        last = min(count, first + ceil(max(1, viewport.height()) / self.PITCH) + 4)
        wanted = set(range(first, last))
        available = [card for i, card in self.indices.items() if i not in wanted]
        available += [card for card in self.rows if card not in self.indices.values()]
        retained = {i: card for i, card in self.indices.items() if i in wanted}
        p.playlist_items_widget.setUpdatesEnabled(False)
        try:
            for i in range(first, last):
                item = p.all_items_data[i]
                card = retained.get(i)
                if card is None:
                    card = available.pop() if available else self._new_card(i, item)
                    self._bind(card, i, item)
                    retained[i] = card
                card.setGeometry(self.MARGIN, self.MARGIN + i * self.PITCH,
                                 max(1, viewport.width() - 20), self.ROW_HEIGHT)
                card.show()
                thumb = card._playlist_thumb
                visible = card.y() + self.ROW_HEIGHT > y and card.y() < y + viewport.height()
                thumb.setProperty('playlist_visible', visible)
                if visible:
                    thumb._start_async_loading()
                elif thumb._current_worker:
                    thumb._current_worker.cancel()
                    thumb._current_worker = None
            for card in available:
                card.hide()
                card._playlist_thumb.setProperty('playlist_visible', False)
                if card._playlist_thumb._current_worker:
                    card._playlist_thumb._current_worker.cancel()
                    card._playlist_thumb._current_worker = None
            self.indices = retained
            p.cards_map = {p.all_items_data[i].id: card for i, card in retained.items()}
            p.loaded_count = len(retained)
            p.is_loading = False
        finally:
            p.playlist_items_widget.setUpdatesEnabled(True)

    def mark(self, media_id):
        p = self.page
        old_id = p.current_playing_id
        if old_id in p.cards_map:
            p.set_card_normal_style(p.cards_map[old_id])
        p.current_playing_id = media_id
        index = self.index_by_id.get(media_id)
        if index is not None:
            bar = p.playlist_scroll.verticalScrollBar()
            top = self.MARGIN + index * self.PITCH
            bottom = top + self.ROW_HEIGHT
            if top < bar.value():
                bar.setValue(top)
            elif bottom > bar.value() + p.playlist_scroll.viewport().height():
                bar.setValue(bottom - p.playlist_scroll.viewport().height())
            self.render()
            if media_id in p.cards_map:
                p.set_card_active_style(p.cards_map[media_id])
        self.update_counter()


def playlist_view(page):
    if not hasattr(page, '_playlist_view'):
        page._playlist_view = PlaylistViewport(page)
    return page._playlist_view
