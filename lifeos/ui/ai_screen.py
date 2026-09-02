"""
lifeOS AI Console Screen (Tab 6)
================================
Dedicated AI cognitive console with the 4 narrow skills:
1. Plan tomorrow ([1])
2. Journal recap ([2])
3. Weekly pattern brief ([3])
4. Inbox triage ([4])
Strict human-in-the-loop: Visible diffs + explicit accept keys only.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Static

from lifeos.core.models import ActionStatus, BlockKind
from lifeos.ui.ai_modal import AIDraftModal
from lifeos.ui.themes import Theme
from lifeos.ui.widgets import BottomStatusBar, HeaderBar, ToastRail


class AIConsoleContentView(Static):
    """Render the AI Copilot console interactive dashboard."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs
        w = self.size.width or 80

        ai_available = app.ai.is_available
        model_name = app.ai.model

        t = Text()
        t.append("AI COPILOT CONSOLE\n", style=f"bold {p.accent_hi}")
        t.append(f"{g.line_horiz * (w - 4)}\n\n", style=f"{p.line}")

        if not ai_available:
            t.append("  AI status: ", style=f"{p.text_dim}")
            t.append("OFFLINE (Local-only mode)\n", style=f"bold {p.state_warn}")
            t.append("  Set OPENROUTER_API_KEY in ~/.lifeos/.env to enable live OpenRouter generation.\n", style=f"{p.text_faint}")
            t.append("  All 4 cognitive skills remain fully functional with deterministic local reasoning.\n\n", style=f"{p.text}")
        else:
            t.append("  AI status: ", style=f"{p.text_dim}")
            t.append(f"ONLINE · Model: {model_name}\n", style=f"bold {p.state_ok}")
            t.append("  Narrow cognitive skills · Zero autonomous mutations · Strict human-in-the-loop review\n\n", style=f"{p.text_faint}")

        t.append("COGNITIVE SKILLS (Press key to trigger draft):\n\n", style=f"bold {p.accent}")

        skills = [
            ("1", "Plan Tomorrow", "Synthesize active outcomes + capacity budget into 3-priority proposal"),
            ("2", "Journal Recap", "Extract events, decisions, commitments & open loops as reviewable draft"),
            ("3", "Weekly Pattern Brief", "Synthesize schedule reliability & failure clusters with evidence citations"),
            ("4", "Inbox Triage", "Triage raw capture backlog into concrete next actions or projects"),
        ]

        for key, name, desc in skills:
            t.append(f"  [", style=f"{p.line}")
            t.append(key, style=f"bold {p.accent_hi}")
            t.append(f"]  {name:<22} ", style=f"bold {p.text_hi}")
            t.append(f"— {desc}\n\n", style=f"{p.text_dim}")

        t.append(f"{g.line_horiz * (w - 4)}\n\n", style=f"{p.line}")
        t.append("RECENT PROPOSALS & CONVERSATION LOGS:\n\n", style=f"bold {p.accent}")
        
        last_prop = getattr(app, "_last_ai_proposal", None)
        if last_prop:
            t.append(f"  {g.bullet_sub} Last proposal: {last_prop.get('title', 'Plan')}\n", style=f"bold {p.text_hi}")
            t.append(f"    Evidence: {last_prop.get('evidence', 'Local telemetry')}\n\n", style=f"{p.text_dim}")
        else:
            t.append("  No active AI drafts pending review.\n", style=f"{p.text_dim}")

        return t


class AIView(Widget):
    """Tab 6 view container."""

    def compose(self) -> ComposeResult:
        with Vertical(id="ai_container"):
            yield AIConsoleContentView(id="ai_console_content")

    def refresh_view(self) -> None:
        try:
            self.query_one(AIConsoleContentView).refresh()
        except Exception:
            pass


class AIScreen(Screen):
    """Full AI Screen for standalone navigation."""

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="topbar")
        yield AIView(id="ai_view")
        yield ToastRail(id="toast")
        yield BottomStatusBar(id="footer")

    def on_mount(self) -> None:
        self.refresh_ai()

    def refresh_ai(self) -> None:
        try:
            self.query_one(AIView).refresh_view()
        except Exception:
            pass
