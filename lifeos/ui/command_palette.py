"""
lifeOS Command Palette Modal
============================
Quick filterable command launcher triggered by `:` from any screen.
"""

from __future__ import annotations

from typing import List, Optional, Tuple
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from lifeos.ui.themes import Theme

COMMANDS = [
    ("today", "Open Today Command Center", ":today"),
    ("plan", "Open Operational Plan Timeline", ":plan"),
    ("projects", "Open Projects & Actions", ":projects"),
    ("journal", "Open Plain-Text Journal", ":journal"),
    ("review", "Open Sunday Weekly Review", ":review"),
    ("capture", "Quick Capture thought to Inbox", ":capture"),
    ("close", "Close Day (90-second retrospective)", ":close"),
    ("ai", "Open AI Copilot Planner", ":ai"),
    ("sync", "Force Cloud Sync with Supabase", ":sync"),
    ("theme", "Cycle Visual Theme (lifeos / phosphor / amber)", ":theme"),
    ("quit", "Quit lifeOS", ":quit"),
]


class CommandPaletteModal(ModalScreen[Optional[str]]):
    """
    Searchable palette of commands.
    """

    def __init__(self):
        super().__init__()
        self.filtered_commands = list(COMMANDS)
        self.cursor_idx = 0

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Static(id="palette_header")
            yield Input(placeholder="Type a command... (e.g. today, plan, projects, ai, sync)", id="palette_input")
            yield Static(id="palette_list")
            yield Static(id="palette_footer")

    def on_mount(self) -> None:
        th: Theme = self.app.theme_obj
        p = th.palette
        g = th.glyphs

        hdr = self.query_one("#palette_header", Static)
        t_hdr = Text()
        t_hdr.append(f"{g.dot_open} COMMAND PALETTE\n", style=f"bold {p.accent_hi}")
        t_hdr.append(f"{g.line_horiz * 55}\n", style=f"{p.line}")
        hdr.update(t_hdr)

        foot = self.query_one("#palette_footer", Static)
        t_foot = Text()
        t_foot.append("\n  [", style=f"{p.line}")
        t_foot.append("↑/↓", style=f"bold {p.accent_hi}")
        t_foot.append("] select   [", style=f"{p.line}")
        t_foot.append("Enter", style=f"bold {p.accent_hi}")
        t_foot.append("] run   [", style=f"{p.line}")
        t_foot.append("Esc", style=f"bold {p.accent_hi}")
        t_foot.append("] dismiss", style=f"{p.line}")
        foot.update(t_foot)

        self._refresh_list()
        self.query_one("#palette_input", Input).focus()

    def _refresh_list(self) -> None:
        th: Theme = self.app.theme_obj
        p = th.palette
        g = th.glyphs

        lview = self.query_one("#palette_list", Static)
        t = Text()

        if not self.filtered_commands:
            t.append("  No matching commands found.\n", style=f"{p.text_dim}")
            lview.update(t)
            return

        for idx, (cmd_id, desc, shortcut) in enumerate(self.filtered_commands[:7]):
            is_selected = (idx == self.cursor_idx)
            rail = f" {g.line_vert} " if is_selected else "   "
            rail_style = p.accent_hi if is_selected else p.line
            t.append(rail, style=rail_style)

            cmd_style = f"bold {p.accent_hi}" if is_selected else p.text_hi
            t.append(f"{shortcut:<12} ", style=cmd_style)
            t.append(f"{desc}\n", style=f"bold {p.text}" if is_selected else p.text_dim)

        lview.update(t)

    def on_input_changed(self, event: Input.Changed) -> None:
        query = event.value.strip().lower().lstrip(":")
        if not query:
            self.filtered_commands = list(COMMANDS)
        else:
            self.filtered_commands = [
                c for c in COMMANDS if query in c[0].lower() or query in c[1].lower()
            ]
        self.cursor_idx = 0
        self._refresh_list()

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
            event.stop()
        elif event.key == "up":
            if self.filtered_commands:
                self.cursor_idx = (self.cursor_idx - 1) % len(self.filtered_commands[:7])
                self._refresh_list()
            event.stop()
        elif event.key == "down":
            if self.filtered_commands:
                self.cursor_idx = (self.cursor_idx + 1) % len(self.filtered_commands[:7])
                self._refresh_list()
            event.stop()
        elif event.key == "enter":
            if self.filtered_commands and self.cursor_idx < len(self.filtered_commands):
                cmd_id = self.filtered_commands[self.cursor_idx][0]
                self.dismiss(cmd_id)
            else:
                self.dismiss(None)
            event.stop()
