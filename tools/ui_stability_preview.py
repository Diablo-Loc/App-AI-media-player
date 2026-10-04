"""Render the same widgets at wide/compact widths using isolated synthetic data."""
from tools.ui_preview import isolated_window, populate, pump, ROOT


def render():
    output = ROOT / "docs/ui/stability"
    output.mkdir(parents=True, exist_ok=True)
    with isolated_window() as (window, root):
        populate(window, root)
        window.toggle_nav_animation()
        pump(350)
        window.sidebar_container.grab().save(str(output / "after-collapsed.png"))
        for width in (1280, 1000, 990, 900, 820, 760):
            window.resize(width, 820)
            pump(350)
            window.grab().save(str(output / f"layout-{width}.png"))
        window.content_stack.setCurrentIndex(3)
        pump(300)
        window.grab().save(str(output / "download-compact.png"))
        window.resize(1280, 820)
        pump(350)
        window.grab().save(str(output / "download-wide.png"))


if __name__ == "__main__":
    render()
