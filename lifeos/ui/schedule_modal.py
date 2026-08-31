"""
lifeOS Schedule Time Block Modal
================================
Schedule an action into a focus block on today's timeline.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

from lifeos.core.models import Action, BlockKind
from lifeos.ui.themes import Theme


class ScheduleBlockModal(ModalScreen[Optional[Dict[str, Any]]]):
    """
    Prompt for start time and duration to schedule a focus block.
    """

    def __init__(self, action: Optional[Action] = None, default_starts_at: str = "09:00", default_mins: int = 60):
        super().__init__()
        self.action = action
        self.default_starts = default_starts_at
        self.default_mins = default_mins

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Static(id="sched_header")
            yield Label("Start Time (HH:MM 24h format):", classes="prompt-lbl")
            yield Input(value=self.default_starts, id="inp_start")

            yield Label("Duration in minutes (e.g. 30, 45, 60, 90):", classes="prompt-lbl")
            yield Input(value=str(self.default_mins), id="inp_duration")

            yield Label("Block Kind (deep_work | routine | admin | buffer):", classes="prompt-lbl")
            yield Input(value="deep_work", id="inp_kind")

            yield Static(id="sched_footer")

    def on_mount(self) -> None:
        th: Theme = self.app.theme_obj
        p = th.palette
        g = th.glyphs

        hdr = self.query_one("#sched_header", Static)
        t_hdr = Text()
        t_hdr.append(f"{g.dot_open} SCHEDULE FOCUS BLOCK\n", style=f"bold {p.accent_hi}")
        if self.action:
            t_hdr.append(f"  Action: {self.action.title}\n", style=f"bold {p.text_hi}")
        t_hdr.append(f"{g.line_horiz * 60}\n", style=f"{p.line}")
        hdr.update(t_hdr)

        foot = self.query_one("#sched_footer", Static)
        t_foot = Text()
        t_foot.append("\n  [", style=f"{p.line}")
        t_foot.append("Enter / Tab", style=f"bold {p.accent_hi}")
        t_foot.append("] next field   [", style=f"{p.line}")
        t_foot.append("Ctrl+S", style=f"bold {p.accent_hi}")
        t_foot.append("] Confirm & Block   [", style=f"{p.line}")
        t_foot.append("Esc", style=f"bold {p.accent_hi}")
        t_foot.append("] Cancel", style=f"{p.line}")
        foot.update(t_foot)

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
            event.stop()
        elif event.key == "ctrl+s":
            self._submit()
            event.stop()
        elif event.key == "enter":
            inp1 = self.query_one("#inp_start", Input)
            inp2 = self.query_one("#inp_duration", Input)
            inp3 = self.query_one("#inp_kind", Input)

            if inp1.has_focus:
                inp2.focus()
            elif inp2.has_focus:
                inp3.focus()
            elif inp3.has_focus:
                self._submit()
            event.stop()

    def _submit(self) -> None:
        starts = self.query_one("#inp_start", Input).value.strip() or "09:00"
        dur_str = self.query_one("#inp_duration", Input).value.strip() or "60"
        kind_str = self.query_one("#inp_kind", Input).value.strip().lower() or "deep_work"

        try:
            dur = int(dur_str)
        except ValueError:
            dur = 60

        # Calculate ends_at
        try:
            hh, mm = map(int, starts.split(":"))
            total_m = hh * 60 + mm + dur
            end_hh = (total_m // 60) % 24
            end_mm = total_m % 60
            ends = f"{end_hh:02d}:{end_mm:02d}"
        except Exception:
            ends = "10:30"

        kind = BlockKind.DEEP_WORK
        if "routine" in kind_str:
            kind = BlockKind.ROUTINE
        elif "admin" in kind_str:
            kind = BlockKind.ADMIN
        elif "buf" in kind_str:
            kind = BlockKind.BUFFER

        self.dismiss({
            "starts_at": starts,
            "ends_at": ends,
            "duration": dur,
            "kind": kind,
            "action_id": self.action.id if self.action else None,
        })
