"""
lifeOS Daily Close Modal (90-second reflection flow)
===================================================
Appends execution evidence and structured answers to the daily plain-text journal.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional, Tuple
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

from lifeos.ui.themes import Theme


class DailyCloseModal(ModalScreen[Optional[Dict[str, str]]]):
    """
    90-second daily retrospective & tomorrow primer.
    """

    def __init__(self, date_str: str, execution_stats: Dict[str, Any]):
        super().__init__()
        self.date_str = date_str
        self.stats = execution_stats

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Static(id="close_header")
            yield Static(id="close_stats")

            yield Label("1. What moved forward today?", classes="prompt-lbl")
            yield Input(placeholder="e.g. Shipped schema migrations, closed 2 priorities", id="ans_forward")

            yield Label("2. What blocked me?", classes="prompt-lbl")
            yield Input(placeholder="e.g. Afternoon context switching, vague initial task", id="ans_blocked")

            yield Label("3. What is tomorrow's first physical action?", classes="prompt-lbl")
            yield Input(placeholder="e.g. Build Today Command Center in today_screen.py", id="ans_tomorrow")

            yield Static(id="close_footer")

    def on_mount(self) -> None:
        th: Theme = self.app.theme_obj
        p = th.palette
        g = th.glyphs

        d_obj = datetime.date.fromisoformat(self.date_str)
        date_title = d_obj.strftime("%a, %b %d").upper()

        hdr = self.query_one("#close_header", Static)
        t_hdr = Text()
        t_hdr.append(f"{g.dot_open} ", style=f"bold {p.accent_hi}")
        t_hdr.append(f"CLOSE DAY · {date_title}\n", style=f"bold {p.text_hi}")
        hdr.update(t_hdr)

        stats_view = self.query_one("#close_stats", Static)
        t_stats = Text()
        t_stats.append("  EXECUTION RECAP\n", style=f"bold {p.accent}")
        t_stats.append(f"  Planned deep work: ", style=f"{p.text_dim}")
        t_stats.append(f"{self.stats.get('planned_str', '3h 30m')}   ", style=f"bold {p.text_hi}")
        t_stats.append(f"Actual: ", style=f"{p.text_dim}")
        t_stats.append(f"{self.stats.get('actual_str', '2h 10m')}\n", style=f"bold {p.state_ok}")
        t_stats.append(f"  Priorities completed: ", style=f"{p.text_dim}")
        t_stats.append(f"{self.stats.get('priorities_done', 0)} / {self.stats.get('priorities_total', 3)}   ", style=f"bold {p.accent_hi}")
        t_stats.append(f"Routines: ", style=f"{p.text_dim}")
        t_stats.append(f"{self.stats.get('routines_done', 0)} / {self.stats.get('routines_total', 5)}\n", style=f"bold {p.text_hi}")
        stats_view.update(t_stats)

        foot = self.query_one("#close_footer", Static)
        t_foot = Text()
        t_foot.append("\n  [", style=f"{p.line}")
        t_foot.append("Enter / Tab", style=f"bold {p.accent_hi}")
        t_foot.append("] next field   [", style=f"{p.line}")
        t_foot.append("Ctrl+S", style=f"bold {p.accent_hi}")
        t_foot.append("] append to journal & bank day   [", style=f"{p.line}")
        t_foot.append("Esc", style=f"bold {p.accent_hi}")
        t_foot.append("] cancel", style=f"{p.line}")
        foot.update(t_foot)

        inp1 = self.query_one("#ans_forward", Input)
        inp1.focus()

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
            event.stop()
        elif event.key in ("ctrl+s",):
            self._submit()
            event.stop()
        elif event.key == "enter":
            # If on the last field, submit; otherwise focus next
            inp1 = self.query_one("#ans_forward", Input)
            inp2 = self.query_one("#ans_blocked", Input)
            inp3 = self.query_one("#ans_tomorrow", Input)

            if inp1.has_focus:
                inp2.focus()
            elif inp2.has_focus:
                inp3.focus()
            elif inp3.has_focus:
                self._submit()
            event.stop()

    def _submit(self) -> None:
        q1 = self.query_one("#ans_forward", Input).value.strip()
        q2 = self.query_one("#ans_blocked", Input).value.strip()
        q3 = self.query_one("#ans_tomorrow", Input).value.strip()

        self.dismiss({
            "forward": q1,
            "blocked": q2,
            "tomorrow": q3,
        })
