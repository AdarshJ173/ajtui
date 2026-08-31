"""
lifeOS Today Command Center Screen
==================================
The primary operational cockpit:
- Single actionable NOW card with [START] trigger
- Today's Three outcome-bearing priorities
- Deep work capacity budget (planned vs available)
- Compact routines strip
- Quick capture indicator
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Static

from lifeos.core.models import ActionStatus, BlockKind, BlockStatus, DailyPriority, SyncStateEnum
from lifeos.ui.themes import Theme, fit, progress_bar_cells


class NowCardView(Static):
    """Exactly one Now card showing the active block or next startable step."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs

        w = self.size.width or 80
        now_data = app.db.get_now_card(app.current_date.strftime("%Y-%m-%d"), app.now_time_str[:5])

        t = Text()
        t.append("NOW ", style=f"bold {p.accent_hi}")
        rule_len = max(2, w - 6)
        t.append(f"{g.line_horiz * rule_len}\n", style=f"{p.line}")

        if not now_data:
            t.append("  All scheduled blocks and priorities completed for today.\n", style=f"{p.state_ok}")
            t.append("  Press [", style=f"{p.text_dim}")
            t.append("I", style=f"bold {p.accent_hi}")
            t.append("] to capture new ideas or [", style=f"{p.text_dim}")
            t.append("X", style=f"bold {p.accent_hi}")
            t.append("] to close the day.", style=f"{p.text_dim}")
            return t

        time_w = now_data.get("time_window", "Now")
        title = now_data.get("title", "Focus Session")
        mins = now_data.get("minutes", 30)
        proj = now_data.get("project_title", "")
        is_active = now_data.get("is_active", False)

        t.append(f"  {time_w:<12} ", style=f"{p.text_dim}")
        t.append(f"{g.bullet_sub} ", style=f"bold {p.accent_hi}")
        t.append(f"{title:<40}", style=f"bold {p.text_hi}")
        if is_active:
            t.append(" [ACTIVE FOCUS] ", style=f"bold {p.on_accent} on {p.state_warn}")
        else:
            t.append(" [START: F] ", style=f"bold {p.on_accent} on {p.accent_hi}")
        t.append("\n")

        t.append(f"  Project / Context: {proj} · {mins}m planned\n", style=f"{p.text_faint}")
        return t


class TodaysThreeView(Static):
    """Today's Three outcome-bearing priority commitments."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs

        w = self.size.width or 80
        date_str = app.current_date.strftime("%Y-%m-%d")
        priorities = app.db.get_daily_priorities(date_str)

        t = Text()
        t.append("TODAY'S THREE ", style=f"bold {p.accent_hi}")
        rule_len = max(2, w - 16)
        t.append(f"{g.line_horiz * rule_len}\n", style=f"{p.line}")

        if not priorities:
            t.append("  No commitments locked for today.\n", style=f"{p.text_dim}")
            t.append("  Press [", style=f"{p.text_dim}")
            t.append("P", style=f"bold {p.accent_hi}")
            t.append("] to pick actions from Projects or [", style=f"{p.text_dim}")
            t.append("A", style=f"bold {p.accent_hi}")
            t.append("] to add a concrete priority.", style=f"{p.text_dim}")
            return t

        for idx, prio in enumerate(priorities):
            act = prio.action
            if not act:
                continue

            is_selected = (idx == getattr(app, "priority_cursor_idx", 0))
            is_done = (act.status == ActionStatus.DONE)

            prefix = " "
            rail_style = p.accent_hi if is_selected else p.line
            t.append(f" {g.line_vert} " if is_selected else "   ", style=rail_style)

            # Checkbox
            cb = f"[{g.check}]" if is_done else "[ ]"
            cb_style = p.state_ok if is_done else (p.accent_hi if is_selected else p.text_dim)
            t.append(f"{prio.rank}. {cb} ", style=cb_style)

            # Title
            title_style = f"strike {p.text_faint}" if is_done else (f"bold {p.text_hi}" if is_selected else p.text)
            t.append(f"{act.title:<38} ", style=title_style)

            # Meta
            p_name = act.project_title or "General"
            t.append(f"{act.estimate_minutes}m · {p_name}\n", style=p.text_dim)

        return t


class CommitmentsCardView(Static):
    """Capacity budget tracker."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs

        date_str = app.current_date.strftime("%Y-%m-%d")
        budget = app.db.get_day_capacity_budget(date_str)

        t = Text()
        t.append("COMMITMENTS\n", style=f"bold {p.accent}")
        t.append(f"  {budget['planned_str']} planned\n", style=f"bold {p.text_hi}")
        if budget["overcommitted"]:
            t.append(f"  ⚠ OVERBUDGET\n", style=f"bold {p.state_warn}")
        else:
            t.append(f"  {budget['available_str']} available\n", style=f"{p.state_ok}")
        t.append(f"  (Max: {budget['capacity_str']})", style=f"{p.text_faint}")
        return t


class RoutinesCompactCardView(Static):
    """Subordinate routines compact summary."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs

        date_str = app.current_date.strftime("%Y-%m-%d")
        tasks = app.db.get_tasks()
        comps = app.db.get_day_completions(date_str)

        total = len(tasks)
        done = sum(1 for c in comps.values() if c.done)
        pct = int((done / total * 100)) if total > 0 else 0

        bar = progress_bar_cells(done / total if total > 0 else 0, 8, g)

        t = Text()
        t.append("ROUTINES\n", style=f"bold {p.accent}")
        t.append(f"  {done}/{total} complete\n", style=f"bold {p.text_hi}")
        t.append(f"  {bar} {pct}%\n", style=f"{p.accent_hi}")
        t.append(f"  [Space] on habits", style=f"{p.text_faint}")
        return t


class CaptureCardView(Static):
    """Quick capture prompt and inbox count."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs

        inbox_items = app.db.get_inbox_items()
        count = len(inbox_items)

        t = Text()
        t.append("CAPTURE\n", style=f"bold {p.accent}")
        t.append(f"  [", style=f"{p.line}")
        t.append("I", style=f"bold {p.accent_hi}")
        t.append(f"] Inbox: {count}\n", style=f"bold {p.text_hi}")
        t.append('  "Anything on your mind?"\n', style=f"italic {p.text_dim}")
        t.append("  Instant capture", style=f"{p.text_faint}")
        return t
