from __future__ import annotations

from sick.tui.app import SickApp


def run_tui(agent) -> None:
    """Launch the interactive TUI against a SickAgent."""
    SickApp(agent).run()