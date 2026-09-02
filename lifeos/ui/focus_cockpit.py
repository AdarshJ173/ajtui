"""
lifeOS Focus Cockpit
====================
Distraction-free narrowed focus environment matching Phase 5 specification:
- Active task / outcome
- Big MM:SS countdown timer with elapsed / remaining
- [D] Distraction capture (dumps thought to inbox without leaving cockpit)
- [Space] Pause / resume
- [Esc] End early -> records completed / partial / skipped + actual_minutes
- Live session notes field
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

from lifeos.core.models import BlockStatus, TimeBlock
from lifeos.ui.capture_modal import CaptureModal
from lifeos.ui.themes import Theme, progress_bar_cells


class FocusCockpitModal(ModalScreen[Optional[Dict[str, Any]]]):
    """
    Narrows the interface to the single active focus block.
    """

    def __init__(self, block: TimeBlock):
        super().__init__()
        self.block = block
        self.total_seconds = max(60, block.planned_minutes * 60)
        self.elapsed_seconds = 0
        self.is_paused = False
        self._timer: Any = None

    def compose(self) -> ComposeResult:
        with Vertical(classes="focus-box"):
            yield Static(id="focus_header")
            yield Static(id="focus_timer_view")
            yield Label("Live Session Notes / Breadcrumbs:", classes="prompt-lbl")
            yield Input(placeholder="Record key milestones, thoughts, or next step...", id="focus_notes")
            yield Static(id="focus_controls")

    def on_mount(self) -> None:
        self._timer = self.set_interval(1.0, self._tick)
        self._refresh_view()
        inp = self.query_one("#focus_notes", Input)
        if self.block.notes:
            inp.value = self.block.notes

    def _tick(self) -> None:
        if not self.is_paused:
            self.elapsed_seconds += 1
            self._refresh_view()

    def _refresh_view(self) -> None:
        th: Theme = self.app.theme_obj
        p = th.palette
        g = th.glyphs

        remaining_sec = max(0, self.total_seconds - self.elapsed_seconds)
        rem_m = remaining_sec // 60
        rem_s = remaining_sec % 60
        elap_m = self.elapsed_seconds // 60
        elap_s = self.elapsed_seconds % 60

        # Header
        hdr = self.query_one("#focus_header", Static)
        t_hdr = Text()
        t_hdr.append(f"{g.focus_dot} FOCUS COCKPIT · ", style=f"bold {p.accent_hi}")
        kind_str = self.block.kind.value.replace("_", " ").upper()
        t_hdr.append(f"{kind_str}\n", style=f"bold {p.text_hi}")
        t_title = self.block.action.title if self.block.action else (self.block.notes or "Deep Work Block")
        t_hdr.append(f"  {t_title}\n", style=f"bold {p.text_hi}")
        if self.block.action and self.block.action.project_title:
            t_hdr.append(f"  Project: {self.block.action.project_title}\n", style=f"{p.accent}")
        t_hdr.append(f"{g.line_horiz * 65}\n", style=f"{p.line}")
        hdr.update(t_hdr)

        # Big Countdown Timer View
        tview = self.query_one("#focus_timer_view", Static)
        t_time = Text()
        status_lbl = "PAUSED" if self.is_paused else "ACTIVE FOCUS"
        status_color = p.state_warn if self.is_paused else p.state_ok

        t_time.append(f"   REMAINING:  ", style=f"{p.text_dim}")
        t_time.append(f"{rem_m:02d}:{rem_s:02d}      ", style=f"bold {p.accent_hi}")
        t_time.append(f"ELAPSED:  ", style=f"{p.text_dim}")
        t_time.append(f"{elap_m:02d}:{elap_s:02d}      ", style=f"bold {p.text}")
        t_time.append(f"[{status_lbl}]\n\n", style=f"bold {status_color}")

        frac = min(1.0, self.elapsed_seconds / self.total_seconds) if self.total_seconds > 0 else 1.0
        bar = progress_bar_cells(frac, 30, g)
        t_time.append(f"   {bar} {int(frac * 100)}%\n", style=f"bold {p.accent_hi}")
        tview.update(t_time)

        # Controls
        ctrls = self.query_one("#focus_controls", Static)
        t_c = Text()
        t_c.append("\n  [", style=f"{p.line}")
        t_c.append("Space / Ctrl+P", style=f"bold {p.accent_hi}")
        t_c.append("] Pause/Resume   [", style=f"{p.line}")
        t_c.append("D / Ctrl+I", style=f"bold {p.accent_hi}")
        t_c.append("] Distraction Capture   [", style=f"{p.line}")
        t_c.append("Esc / Ctrl+S", style=f"bold {p.accent_hi}")
        t_c.append("] Finish Block", style=f"{p.line}")
        ctrls.update(t_c)

    def on_key(self, event: events.Key) -> None:
        k = event.key.lower()
        if k in ("ctrl+p", "pause"):
            self.is_paused = not self.is_paused
            self._refresh_view()
            event.stop()
        elif k in ("d", "ctrl+i") and not self.query_one("#focus_notes", Input).has_focus:
            # Distraction capture
            def on_distraction(res):
                if res:
                    _, content = res
                    self.app.db.add_inbox_item(content, source="focus_distraction")
                    self.app.sync_engine.notify_local_mutation()
                    self.app.set_toast(f"Distraction captured to inbox: '{content}'")
            self.app.push_screen(CaptureModal(), on_distraction)
            event.stop()
        elif k in ("escape", "ctrl+s"):
            notes = self.query_one("#focus_notes", Input).value.strip()
            actual_mins = max(1, self.elapsed_seconds // 60)
            is_full = self.elapsed_seconds >= (self.total_seconds * 0.8)
            self.dismiss({
                "status": BlockStatus.COMPLETED if is_full else BlockStatus.PLANNED,
                "actual_minutes": actual_mins,
                "notes": notes,
            })
            event.stop()
