"""Presentation-only gutters; preserve the wrapper used by all other pages."""
from PySide6.QtCore import QObject

PAGE_GUTTER = 12


class ForYouSpacing(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.wrapper = window.grid_main_page.layout()
        self.original_margins = self.wrapper.contentsMargins()
        self.original_spacing = self.wrapper.spacing()
        self.browser_spacing = window.browser_layout.spacing()
        window.content_stack.currentChanged.connect(self.sync)
        self.sync()

    def sync(self, *_):
        is_for_you = self.window.content_stack.currentWidget() is self.window.foryou_page
        if is_for_you:
            self.wrapper.setContentsMargins(0, 0, 0, 0)
            self.wrapper.setSpacing(0)
            self.window.browser_layout.setSpacing(0)
        else:
            self.wrapper.setContentsMargins(self.original_margins)
            self.wrapper.setSpacing(self.original_spacing)
            self.window.browser_layout.setSpacing(self.browser_spacing)


def install_for_you_spacing(window):
    if not hasattr(window, '_for_you_spacing'):
        window._for_you_spacing = ForYouSpacing(window)
