"""
lifeOS AI Draft Review Modal
============================
Human-in-the-loop review of AI proposed plans, summaries, and pattern briefs.
Every AI output is a draft with evidence citations.
[A]ccept · [E]dit · [R]egenerate · [D]ismiss
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from lifeos.ui.themes import Theme


class AIDraftModal(ModalScreen[Optional[str]]):
    """
    Review and accept / edit / dismiss AI generated drafts.
    """

    def __init__(self, title: str, draft_text: str, evidence: str):
        super().__init__()
        self.draft_title = title
        self.draft_text = draft_text
        self.evidence = evidence

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Static(id="ai_header")
            yield Static(id="ai_content")
            yield Static(id="ai_evidence")
            yield Static(id="ai_footer")

    def on_mount(self) -> None:
        th: Theme = self.app.theme_obj
        p = th.palette
        g = th.glyphs

        hdr = self.query_one("#ai_header", Static)
        t_hdr = Text()
        t_hdr.append(f"{g.dot_open} AI COPILOT · ", style=f"bold {p.accent_hi}")
        t_hdr.append(f"{self.draft_title.upper()}\n", style=f"bold {p.text_hi}")
        t_hdr.append(f"{g.line_horiz * 65}\n", style=f"{p.line}")
        hdr.update(t_hdr)

        cnt = self.query_one("#ai_content", Static)
        t_cnt = Text()
        t_cnt.append("PROPOSED DRAFT:\n", style=f"bold {p.accent}")
        t_cnt.append(f"{self.draft_text}\n\n", style=f"{p.text_hi}")
        cnt.update(t_cnt)

        evi = self.query_one("#ai_evidence", Static)
        t_evi = Text()
        t_evi.append(f"  {g.bullet_sub} Evidence: {self.evidence}\n", style=f"italic {p.text_dim}")
        evi.update(t_evi)

        foot = self.query_one("#ai_footer", Static)
        t_foot = Text()
        t_foot.append("\n  [", style=f"{p.line}")
        t_foot.append("A", style=f"bold {p.state_ok}")
        t_foot.append("] Accept Draft   [", style=f"{p.line}")
        t_foot.append("E", style=f"bold {p.accent_hi}")
        t_foot.append("] Edit in Journal   [", style=f"{p.line}")
        t_foot.append("R", style=f"bold {p.accent}")
        t_foot.append("] Regenerate   [", style=f"{p.line}")
        t_foot.append("D / Esc", style=f"bold {p.danger}")
        t_foot.append("] Dismiss", style=f"{p.line}")
        foot.update(t_foot)

    def on_key(self, event: events.Key) -> None:
        k = event.key.lower()
        if k in ("escape", "d"):
            self.dismiss("dismiss")
            event.stop()
        elif k == "a":
            self.dismiss("accept")
            event.stop()
        elif k == "e":
            self.dismiss("edit")
            event.stop()
        elif k == "r":
            self.dismiss("regenerate")
            event.stop()
