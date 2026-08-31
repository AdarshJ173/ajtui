"""
lifeOS Missed Block Handler Modal
=================================
Missed blocks never silently roll to tomorrow.
Presents exactly three choices:
[R] Reschedule · [S] Shrink · [C] Cancel / Skip
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

from lifeos.core.models import BlockStatus, TimeBlock
from lifeos.ui.themes import Theme


class MissedBlockModal(ModalScreen[Optional[Dict[str, Any]]]):
    """
    Explicit handling of missed or overrun time blocks.
    """

    def __init__(self, block: TimeBlock):
        super().__init__()
        self.block = block

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Static(id="missed_header")
            yield Label("One-line reason if skipping/cancelling (reality check):", classes="prompt-lbl")
            yield Input(placeholder="e.g. Urgent client meeting overran, low afternoon energy", id="skip_reason")
            yield Static(id="missed_choices")

    def on_mount(self) -> None:
        th: Theme = self.app.theme_obj
        p = th.palette
        g = th.glyphs

        hdr = self.query_one("#missed_header", Static)
        t_hdr = Text()
        t_hdr.append(f"⚠ MISSED FOCUS BLOCK\n", style=f"bold {p.state_warn}")
        b_title = self.block.action.title if self.block.action else (self.block.notes or "Focus Block")
        t_hdr.append(f"  {self.block.starts_at}–{self.block.ends_at} · {b_title} ({self.block.planned_minutes}m)\n", style=f"bold {p.text_hi}")
        t_hdr.append("  This planned block window has elapsed without completion.\n", style=f"{p.text_dim}")
        t_hdr.append(f"{g.line_horiz * 60}\n", style=f"{p.line}")
        hdr.update(t_hdr)

        choices = self.query_one("#missed_choices", Static)
        t_c = Text()
        t_c.append("\n  Choose one explicit action:\n", style=f"bold {p.accent}")
        t_c.append("  [", style=f"{p.line}")
        t_c.append("R", style=f"bold {p.accent_hi}")
        t_c.append("] Reschedule to later today   [", style=f"{p.line}")
        t_c.append("S", style=f"bold {p.accent_hi}")
        t_c.append("] Shrink duration   [", style=f"{p.line}")
        t_c.append("C", style=f"bold {p.danger}")
        t_c.append("] Cancel / Skip block\n", style=f"{p.line}")
        t_c.append("  [", style=f"{p.line}")
        t_c.append("Esc", style=f"bold {p.text_dim}")
        t_c.append("] Dismiss", style=f"{p.line}")
        choices.update(t_c)

    def on_key(self, event: events.Key) -> None:
        k = event.key.lower()
        reason = self.query_one("#skip_reason", Input).value.strip()

        if k == "escape":
            self.dismiss(None)
            event.stop()
        elif k == "r":
            self.dismiss({"action": "reschedule"})
            event.stop()
        elif k == "s":
            self.dismiss({"action": "shrink"})
            event.stop()
        elif k == "c":
            self.dismiss({"action": "cancel", "reason": reason or "Skipped without notes"})
            event.stop()
