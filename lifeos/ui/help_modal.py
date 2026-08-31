"""
lifeOS Keyboard Shortcuts & Discoverability Help Overlay
========================================================
Searchable help matrix opened by `?` from any screen.
"""

from __future__ import annotations

from typing import Optional
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from lifeos.ui.themes import Theme

SHORTCUTS = [
    (":", "Command Palette", "Open searchable command launcher"),
    ("?", "Help Overlay", "Show this keybindings cheat sheet"),
    ("P", "Projects Screen", "Manage outcomes, next actions, and blockers"),
    ("L", "Plan Timeline", "View day capacity and schedule time blocks"),
    ("W", "Weekly Review", "Sunday retrospective & pattern insights"),
    ("I", "Global Quick Capture", "Capture thoughts directly to inbox (2s flow)"),
    ("X", "Daily Close", "90-second retrospective & tomorrow primer"),
    ("F", "Focus Cockpit", "Start distraction-free focus timer on Now block"),
    ("B", "Schedule Block", "Block selected action into operational day timeline"),
    ("1-3", "Commit Priorities", "Lock top 1-3 outcome priorities for today"),
    ("J", "Daily Journal", "Open plain-text mirrored daily journal"),
    ("U", "Undo Delete", "Restore soft-deleted item (5s window)"),
    ("S", "Force Sync", "Trigger immediate bidirectional cloud sync"),
    ("T", "Cycle Theme", "Swap palette between lifeos / phosphor / amber"),
    ("Space / Enter", "Toggle Completion", "Check off ritual or priority"),
    ("Q", "Quit", "Exit lifeOS cleanly"),
]


class HelpModal(ModalScreen[None]):
    """
    Searchable keyboard help overlay.
    """

    def __init__(self):
        super().__init__()
        self.filtered = list(SHORTCUTS)

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Static(id="help_header")
            yield Input(placeholder="Search shortcuts... (e.g. project, focus, capture, journal)", id="help_input")
            yield Static(id="help_list")
            yield Static(id="help_footer")

    def on_mount(self) -> None:
        th: Theme = self.app.theme_obj
        p = th.palette
        g = th.glyphs

        hdr = self.query_one("#help_header", Static)
        t_hdr = Text()
        t_hdr.append(f"{g.dot_open} KEYBOARD SHORTCUTS & NAVIGATION\n", style=f"bold {p.accent_hi}")
        t_hdr.append(f"{g.line_horiz * 65}\n", style=f"{p.line}")
        hdr.update(t_hdr)

        foot = self.query_one("#help_footer", Static)
        t_foot = Text()
        t_foot.append("\n  Press [", style=f"{p.line}")
        t_foot.append("Esc / ?", style=f"bold {p.accent_hi}")
        t_foot.append("] to close help", style=f"{p.line}")
        foot.update(t_foot)

        self._refresh_list()
        self.query_one("#help_input", Input).focus()

    def _refresh_list(self) -> None:
        th: Theme = self.app.theme_obj
        p = th.palette

        lview = self.query_one("#help_list", Static)
        t = Text()

        for key, name, desc in self.filtered[:9]:
            t.append(f"  [{key:<10}] ", style=f"bold {p.accent_hi}")
            t.append(f"{name:<20} ", style=f"bold {p.text_hi}")
            t.append(f"{desc}\n", style=p.text_dim)

        lview.update(t)

    def on_input_changed(self, event: Input.Changed) -> None:
        q = event.value.strip().lower()
        if not q:
            self.filtered = list(SHORTCUTS)
        else:
            self.filtered = [
                s for s in SHORTCUTS if q in s[0].lower() or q in s[1].lower() or q in s[2].lower()
            ]
        self._refresh_list()

    def on_key(self, event: events.Key) -> None:
        if event.key in ("escape", "question_mark"):
            self.dismiss(None)
            event.stop()
