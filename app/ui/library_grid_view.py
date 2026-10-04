"""Viewport-sized Library cards; full metadata remains the playback source."""
import math
from collections import deque
from PySide6.QtCore import QObject, QEvent, QRect, QTimer
from .media_card import MediaCard


class LibraryGridView(QObject):
    def __init__(self, window, page):
        super().__init__(page)
        self.window, self.page = window, page
        self.source, self.visible, self.cards = [], [], []
        self.order = []
        self.queries = deque()
        self.query = ''
        self.job = None
        self.closed = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.render)
        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.timeout.connect(self._filter_chunk)
        self.layout = page.grid_layout
        self.layout.setEnabled(False)
        page.scroll_area.viewport().installEventFilter(self)
        page.scroll_area.verticalScrollBar().valueChanged.connect(self.schedule)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.schedule()
        elif event.type() == QEvent.Type.Hide:
            self.timer.stop()
        return False

    def schedule(self, *args):
        if not self.closed and not self.timer.isActive():
            self.timer.start(16)

    def load(self, items):
        self.closed = False
        self.filter_timer.stop()
        self.job = None
        self.queries.clear()
        self.source = list(items)
        self.order = list(self.source)
        self.visible = list(self.source)
        self.query = ''
        self.page.scroll_area.verticalScrollBar().setValue(0)
        self.render()

    def get_playback_playlist(self):
        # The old grid queue included hidden search cards as well.
        return list(self.order)

    def filter(self, text):
        query = text.lower().strip()
        if query == self.query:
            return
        self.query = query
        self.queries.append(query)
        if self.job is None:
            self._start_filter()

    def _start_filter(self):
        query = self.queries.popleft()
        if not query:
            self.job = None
            self.visible = list(self.order)
            if self.queries:
                self._start_filter()
            else:
                self.render()
            return
        self.job = dict(query=query, source=self.order, offset=0, results=[], misses=[])
        self.filter_timer.start(0)

    def _filter_chunk(self):
        job = self.job
        if job is None:
            return
        end = min(len(job['source']), job['offset'] + 500)
        for item in job['source'][job['offset']:end]:
            if job['query'] in item.title.lower():
                job['results'].append(item)
            else:
                job['misses'].append(item)
        job['offset'] = end
        if end < len(job['source']):
            self.filter_timer.start(0)
        else:
            # QGridLayout re-adds matching cards at the end of its item order.
            # Preserve that legacy queue effect without allocating every card.
            if job['results']:
                self.order = job['misses'] + job['results']
            self.job = None
            if self.queries:
                self._start_filter()
            else:
                self.visible = job['results']
                self.render()

    def _publish(self):
        if getattr(self.window, 'grid_layout', None) is self.layout:
            live = [card for card in self.cards if not card.isHidden()]
            self.window.grid_widgets = live
            self.window.card_map = {card.id: card for card in live}

    def render(self):
        if self.closed or not self.page.isVisible():
            return
        viewport = self.page.scroll_area.viewport()
        columns = max(1, viewport.width() // 230)
        margins = self.layout.contentsMargins()
        gap = self.layout.spacing()
        pitch = 210 + gap
        row_count = math.ceil(len(self.visible)/columns)
        height = margins.top() + margins.bottom() + max(0, row_count*pitch-gap)
        self.page.grid_container.setMinimumHeight(height)
        self.page.grid_container.setMinimumWidth(0)
        top = self.page.scroll_area.verticalScrollBar().value()
        first = max(0, (top-margins.top())//pitch-1)
        last = min(row_count, math.ceil((top+viewport.height()-margins.top())/pitch)+1)
        indices = range(first*columns, min(len(self.visible), last*columns))
        needed = len(indices)
        while len(self.cards) > needed:
            card = self.cards.pop()
            card.hide()
            self.layout.removeWidget(card)
            card.deleteLater()
        while len(self.cards) < needed:
            card = MediaCard(self.visible[indices[len(self.cards)]], self.page.grid_container)
            card.clicked.connect(self.window.on_media_clicked)
            card.clicked.connect(self.window.sync_to_foryou)
            # Keep the established grid/widget API; geometry is managed here.
            self.layout.addWidget(card)
            self.cards.append(card)
        available = max(0, viewport.width()-margins.left()-margins.right()-gap*(columns-1))
        width, remainder = divmod(available, columns)
        for card, index in zip(self.cards, indices):
            item = self.visible[index]
            signature = (id(item), item.id, item.title, item.mtime, item.thumbnail)
            if getattr(card, '_row_signature', None) != signature:
                card.bind_media(item)
                card._row_signature = signature
            row, column = divmod(index, columns)
            x = margins.left()+column*(width+gap)+min(column, remainder)
            card.setGeometry(QRect(x, margins.top()+row*pitch,
                                   max(200, width+(column < remainder)), 210))
            card.show()
        self._publish()

    def clear(self):
        self.timer.stop()
        self.filter_timer.stop()
        self.job = None
        self.queries.clear()
        self.order = []
        self.source, self.visible = [], []
        self.query = ''
        for card in self.cards:
            card.hide()
            card.thumb_label.clear()
        self.page.grid_container.setMinimumHeight(0)
        self._publish()


def library_grid(window, page):
    if not hasattr(page, '_library_grid_view'):
        page._library_grid_view = LibraryGridView(window, page)
    return page._library_grid_view
