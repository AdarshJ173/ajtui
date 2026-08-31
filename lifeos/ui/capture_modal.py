"""
lifeOS Global Quick Capture Modal
=================================
Zero-friction capture from any screen (2-second flow).
[Enter] save inbox    [P] attach project    [A] make next action    [Esc] cancel
"""

from __future__ import annotations

from typing import Optional, Tuple
from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

from lifeos.ui.themes import Theme


class CaptureModal(ModalScreen[Optional[Tuple[str, str]]]):
    """
    Global capture modal.
    Returns (action_type, text) where action_type is 'inbox' | 'action' | 'project',
    or None if cancelled.
    """

    def __init__(self, initial_text: str = ""):
        super().__init__()
        self.initial_text = initial_text

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Static(id="capture_header")
            yield Input(
                placeholder="What is on your mind? (concrete physical next step)",
                value=self.initial_text,
                id="capture_input",
            )
            yield Static(id="capture_hints")

    def on_mount(self) -> None:
        th: Theme = self.app.theme_obj
        p = th.palette
        g = th.glyphs

        hdr = self.query_one("#capture_header", Static)
        t_hdr = Text()
        t_hdr.append(f"{g.dot_open} ", style=f"bold {p.accent_hi}")
        t_hdr.append("GLOBAL CAPTURE", style=f"bold {p.text_hi}")
        t_hdr.append("  (Zero categorization friction)", style=f"{p.text_dim}")
        hdr.update(t_hdr)

        hints = self.query_one("#capture_hints", Static)
        t_hint = Text()
        t_hint.append("\n  [", style=f"{p.line}")
        t_hint.append("Enter", style=f"bold {p.accent_hi}")
        t_hint.append("] save inbox   [", style=f"{p.line}")
        t_hint.append("Ctrl+A", style=f"bold {p.accent_hi}")
        t_hint.append("] make next action   [", style=f"{p.line}")
        t_hint.append("Ctrl+P", style=f"bold {p.accent_hi}")
        t_hint.append("] new project   [", style=f"{p.line}")
        t_hint.append("Esc", style=f"bold {p.accent_hi}")
        t_hint.append("] cancel", style=f"{p.line}")
        hints.update(t_hint)

        inp = self.query_one("#capture_input", Input)
        inp.focus()

    def on_key(self, event: events.Key) -> None:
        inp = self.query_one("#capture_input", Input)
        val = inp.value.strip()

        if event.key == "escape":
            self.dismiss(None)
            event.stop()
        elif event.key == "enter":
            if val:
                self.dismiss(("inbox", val))
            else:
                self.dismiss(None)
            event.stop()
        elif event.key in ("ctrl+a", "ctrl+n"):
            if val:
                self.dismiss(("action", val))
            event.stop()
        elif event.key == "ctrl+p":
            if val:
                self.dismiss(("project", val))
            event.stop()
