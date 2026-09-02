"""
lifeOS Operational Plan Timeline Screen (Tab 3)
===============================================
Visual operational day timeline with 1-keystroke scheduling, buffer management,
focus cockpit trigger, drag-equivalent nudging, and missed block resolution.
"""

from __future__ import annotations

import datetime
from typing import Any, List, Optional
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Static

from lifeos.core.models import ActionStatus, BlockKind, BlockStatus, TimeBlock
from lifeos.ui.focus_cockpit import FocusCockpitModal
from lifeos.ui.missed_block_modal import MissedBlockModal
from lifeos.ui.schedule_modal import ScheduleBlockModal
from lifeos.ui.themes import Theme
from lifeos.ui.widgets import BottomStatusBar, HeaderBar, KeyChipBar, ToastRail


class PlanTimelineView(Static):
    """Render the operational day schedule timeline."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs
        w = self.size.width or 80

        date_str = app.current_date.strftime("%Y-%m-%d")
        blocks: List[TimeBlock] = app.db.get_time_blocks(date_str)
        cursor_idx = getattr(self.screen, "block_cursor_idx", 0)
        budget = app.db.get_day_capacity_budget(date_str)

        d_obj = datetime.date.fromisoformat(date_str)
        day_header = d_obj.strftime("%a, %b %d").upper()

        t = Text()
        t.append(f"{day_header:<40}", style=f"bold {p.accent_hi}")
        t.append(f"Capacity: {budget['planned_str']} / {budget['capacity_str']}\n", style=f"{p.accent_hi}")
        t.append(f"{g.line_horiz * max(10, w - 4)}\n\n", style=f"{p.line}")

        if not blocks:
            t.append("  No time blocks scheduled for today.\n", style=f"{p.text_dim}")
            t.append("  Press [", style=f"{p.text_dim}")
            t.append("B", style=f"bold {p.accent_hi}")
            t.append("] to schedule a focus block into your day.", style=f"{p.text_dim}")
            return t

        box_width = min(68, max(20, w - 12))

        t.append(f"      ┌{'─' * box_width}┐\n", style=p.line)

        for idx, b in enumerate(blocks):
            is_selected = (idx == cursor_idx)
            is_done = (b.status == BlockStatus.COMPLETED)
            is_missed = (b.status == BlockStatus.SKIPPED)
            is_active = (b.status == BlockStatus.ACTIVE)

            b_title = b.action.title if b.action else (b.notes or "Focus Session")
            kind_str = b.kind.value.replace("_", " ")

            # Status badge
            stat_str = f"[{b.status.value.upper()}]"
            if is_done:
                stat_style = p.state_ok
            elif is_active:
                stat_style = p.accent_hi
            elif is_missed:
                stat_style = p.danger
            else:
                stat_style = p.text_dim

            # Border line
            rail_style = p.accent_hi if is_selected else p.line

            t.append(f"{b.starts_at} ├", style=rail_style)
            b_label = fit(b_title, box_width - 18)
            t.append(f"─── {b_label} ─── {b.planned_minutes}m ", style=f"bold {p.text_hi}" if is_selected else p.text)
            t.append(f"┤\n", style=p.line)

            t.append(f"{b.ends_at} │", style=p.line)
            t.append(f" {stat_str} {kind_str} ", style=stat_style)
            t.append(f"│\n", style=p.line)

        t.append(f"      └{'─' * box_width}┘\n", style=p.line)
        return t


class PlanView(Widget):
    """Tab 3 View container."""

    def compose(self) -> ComposeResult:
        with Vertical(id="plan_container"):
            yield PlanTimelineView(id="timeline_view")

    def refresh_view(self) -> None:
        try:
            self.query_one(PlanTimelineView).refresh()
        except Exception:
            pass


class PlanScreen(Screen):
    """Full interactive Operational Day Plan Screen."""

    def __init__(self):
        super().__init__()
        self.block_cursor_idx: int = 0

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="topbar")
        yield PlanView(id="plan_view")
        yield ToastRail(id="toast")
        yield BottomStatusBar(id="footer")

    def on_mount(self) -> None:
        self.refresh_timeline()

    def refresh_timeline(self) -> None:
        date_str = self.app.current_date.strftime("%Y-%m-%d")
        blocks = self.app.db.get_time_blocks(date_str)
        if blocks:
            self.block_cursor_idx = max(0, min(len(blocks) - 1, self.block_cursor_idx))
        else:
            self.block_cursor_idx = 0
        try:
            self.query_one(PlanTimelineView).refresh()
        except Exception:
            pass

    def on_key(self, event: events.Key) -> None:
        k = event.key
        k_lower = k.lower()

        if k_lower in ("escape", "q"):
            event.stop()
            self.app.pop_screen()
            return

        date_str = self.app.current_date.strftime("%Y-%m-%d")
        blocks = self.app.db.get_time_blocks(date_str)

        if k_lower in ("up", "k"):
            event.stop()
            if blocks:
                self.block_cursor_idx = (self.block_cursor_idx - 1) % len(blocks)
                self.refresh_timeline()
            return
        elif k_lower in ("down", "j"):
            event.stop()
            if blocks:
                self.block_cursor_idx = (self.block_cursor_idx + 1) % len(blocks)
                self.refresh_timeline()
            return

        # Schedule new block ('B')
        if k_lower == "b":
            event.stop()
            def on_scheduled(data):
                if data:
                    self.app.db.add_time_block(
                        date_str=date_str,
                        starts_at=data["starts_at"],
                        ends_at=data["ends_at"],
                        action_id=data["action_id"],
                        kind=data["kind"],
                        planned_minutes=data["duration"],
                    )
                    self.app.sync_engine.notify_local_mutation()
                    self.refresh_timeline()
                    self.app.set_toast(f"Scheduled focus block: {data['starts_at']}–{data['ends_at']}")

            self.app.push_screen(ScheduleBlockModal(), on_scheduled)
            return

        # Start Focus Cockpit ('Space' / 'Enter')
        if k in ("space", "enter") and blocks:
            event.stop()
            curr_b = blocks[self.block_cursor_idx]

            self.app.db.update_time_block(curr_b.id, status=BlockStatus.ACTIVE)
            self.app.sync_engine.notify_local_mutation()

            def on_focus_complete(res):
                if res:
                    self.app.db.close_time_block(
                        curr_b.id,
                        status=res["status"],
                        actual_minutes=res["actual_minutes"],
                        notes=res.get("notes"),
                    )
                    if curr_b.action_id and res["status"] == BlockStatus.COMPLETED:
                        self.app.db.update_action(curr_b.action_id, status=ActionStatus.DONE)
                    self.app.sync_engine.notify_local_mutation()
                    self.refresh_timeline()
                    self.app.set_toast(f"Focus block completed! ({res['actual_minutes']}m logged)")
                else:
                    self.app.db.update_time_block(curr_b.id, status=BlockStatus.PLANNED)
                    self.refresh_timeline()

            self.app.push_screen(FocusCockpitModal(curr_b), on_focus_complete)
            return

        # Handle Missed Block ('M')
        if k_lower == "m" and blocks:
            event.stop()
            curr_b = blocks[self.block_cursor_idx]
            def on_missed_choice(choice):
                if choice:
                    act = choice.get("action")
                    if act == "cancel":
                        self.app.db.update_time_block(
                            curr_b.id,
                            status=BlockStatus.SKIPPED,
                            notes=choice.get("reason"),
                        )
                        self.app.set_toast("Block marked as skipped (logged to history)")
                    elif act == "reschedule":
                        self.app.db.update_time_block(
                            curr_b.id,
                            starts_at=choice.get("starts_at", curr_b.starts_at),
                            ends_at=choice.get("ends_at", curr_b.ends_at),
                            status=BlockStatus.PLANNED,
                            notes=choice.get("reason"),
                        )
                        self.app.set_toast(f"Rescheduled block to {choice.get('starts_at')}")
                    elif act == "shrink":
                        self.app.db.update_time_block(
                            curr_b.id,
                            planned_minutes=max(15, curr_b.planned_minutes // 2),
                        )
                        self.app.set_toast("Shrank block duration")
                    self.app.sync_engine.notify_local_mutation()
                    self.refresh_timeline()

            self.app.push_screen(MissedBlockModal(curr_b), on_missed_choice)
            return

        # Shrink / Extend duration ('S')
        if k_lower == "s" and blocks:
            event.stop()
            curr_b = blocks[self.block_cursor_idx]
            new_dur = curr_b.planned_minutes + 15 if curr_b.planned_minutes < 120 else 30
            self.app.db.update_time_block(curr_b.id, planned_minutes=new_dur)
            self.app.sync_engine.notify_local_mutation()
            self.refresh_timeline()
            self.app.set_toast(f"Adjusted block duration to {new_dur}m")
            return

        # Delete Block ('D')
        if k_lower == "d" and blocks:
            event.stop()
            curr_b = blocks[self.block_cursor_idx]
            self.app.db.delete_time_block(curr_b.id)
            self.app.sync_engine.notify_local_mutation()
            self.refresh_timeline()
            self.app.set_toast("Deleted time block")
            return
