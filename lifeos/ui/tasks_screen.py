"""
lifeOS Tasks & Routine Habits Screen
====================================
The master routine screen tracking daily rituals, completion semaphores,
streak calculations, and responsive calendar matrix.
"""

from __future__ import annotations

import datetime
from typing import Optional

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen

from lifeos.ui.widgets import (
    BootOverlay,
    HeaderBar,
    HeroBanner,
    KeyChipBar,
    MomentumDock,
    MonthCalendarView,
    TaskListView,
    TextInputModal,
    ToastRail,
)


class TasksScreen(Screen):
    """Main screen displaying daily routine habits, streak dock, and calendar."""

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="topbar")
        yield HeroBanner(id="hero_panel")
        with Horizontal(id="main_content"):
            yield TaskListView(id="routine_list")
            with Vertical(id="calendar_container"):
                yield MonthCalendarView(id="cal_panel")
        yield MomentumDock(id="dock_panel")
        yield ToastRail(id="toast")
        yield KeyChipBar(id="footer")
        with Vertical(id="boot_layer"):
            yield BootOverlay(id="boot")

    def remove_boot_overlay(self) -> None:
        try:
            for widget in self.query("#boot_layer"):
                widget.remove()
        except Exception:
            pass

    def on_mount(self) -> None:
        self.app._apply_layout_mode()
        if getattr(self.app, "booting", False):
            self.app._start_boot()
        else:
            self.remove_boot_overlay()
            self.app.anim_progress = self.app.target_progress

    def on_key(self, event: events.Key) -> None:
        # Boot overlay skip on any key
        if getattr(self.app, "booting", False):
            self.app.ui_animator.cancel("boot")
            self.app._end_boot()
            self.remove_boot_overlay()
            event.stop()
            return

        k = event.key
        k_lower = k.lower()

        # Calendar Interactive Mode
        if getattr(self.app, "calendar_active", False):
            if k_lower in ("escape", "c"):
                self.app.calendar_active = False
                self.app.cal_focus_date = self.app.current_date
                self.app.set_toast(self.app.theme_obj.messages.toast_cal_off)
                self.app._refresh_all_widgets()
                return
            elif k_lower in ("left", "h"):
                self.app._move_cal(-1)
                return
            elif k_lower in ("right", "l"):
                self.app._move_cal(1)
                return
            elif k_lower in ("up", "k"):
                self.app._move_cal(-7)
                return
            elif k_lower in ("down", "j"):
                self.app._move_cal(7)
                return
            elif k in ("space", "enter"):
                self.app.current_date = self.app.cal_focus_date
                self.app.calendar_active = False
                self.app.refresh_data()
                self.app.animate_progress_bar()
                self.app.set_toast(
                    self.app.theme_obj.messages.toast_jumped.format(
                        date=self.app.current_date.strftime("%b %d, %Y")
                    )
                )
                return
            elif k_lower in ("0", "today"):
                self.app.cal_focus_date = datetime.date.today()
                self.app.current_date = self.app.cal_focus_date
                self.app.calendar_active = False
                self.app.refresh_data()
                self.app.animate_progress_bar()
                self.app.set_toast(self.app.theme_obj.messages.toast_today)
                return
            elif k in ("j", "J"):
                self.app.action_open_journal()
                return
            elif k in ("s", "S"):
                self.app.action_force_sync()
                return
            elif k in ("t", "T"):
                self.app.action_cycle_theme()
                return
            elif k_lower == "q":
                self.app.exit()
                return

        # Reorder (shift variants / brackets / ctrl-arrows / alt-arrows)
        if k in ("shift+k", "ctrl+up", "alt+up", "["):
            if self.app.tasks:
                curr = self.app.tasks[self.app.cursor_idx]
                self.app.db.reorder_task(curr.id, -1)
                self.app.cursor_idx = max(0, self.app.cursor_idx - 1)
                self.app.sync_engine.notify_local_mutation()
                self.app.refresh_data()
                self.app.set_toast(
                    self.app.theme_obj.messages.toast_moved.format(
                        dir="up", title=curr.title
                    )
                )
            return

        if k in ("shift+j", "ctrl+down", "alt+down", "]"):
            if self.app.tasks:
                curr = self.app.tasks[self.app.cursor_idx]
                self.app.db.reorder_task(curr.id, 1)
                self.app.cursor_idx = min(len(self.app.tasks) - 1, self.app.cursor_idx + 1)
                self.app.sync_engine.notify_local_mutation()
                self.app.refresh_data()
                self.app.set_toast(
                    self.app.theme_obj.messages.toast_moved.format(
                        dir="down", title=curr.title
                    )
                )
            return

        # List navigation
        if k_lower in ("up", "k"):
            if self.app.tasks:
                self.app.cursor_idx = (self.app.cursor_idx - 1) % len(self.app.tasks)
                self.query_one(TaskListView).refresh()
            return
        elif k_lower in ("down",):
            if self.app.tasks:
                self.app.cursor_idx = (self.app.cursor_idx + 1) % len(self.app.tasks)
                self.query_one(TaskListView).refresh()
            return

        # Open Journal (J or 5)
        elif k_lower == "j" or k == "5":
            self.app.action_open_journal()
            return

        # Force Sync (S)
        elif k in ("s", "S"):
            self.app.action_force_sync()
            return

        # Toggle completion
        elif k in ("space", "enter"):
            if not self.app.tasks:
                self.app.set_toast(self.app.theme_obj.messages.toast_no_tasks)
            else:
                curr = self.app.tasks[self.app.cursor_idx]
                d_str = self.app.current_date.strftime("%Y-%m-%d")
                new_state = self.app.db.toggle_completion(curr.id, d_str)
                self.app.sync_engine.notify_local_mutation()
                self.app.refresh_data()
                self.app.animate_flip(curr.id, new_state)
                self.app.animate_progress_bar()
                msg = self.app.theme_obj.messages
                self.app.set_toast(
                    (msg.toast_done if new_state else msg.toast_undone).format(
                        title=curr.title
                    )
                )
            return

        # Date navigation
        elif k_lower in ("left", "h"):
            self.app._shift_date(-1)
            return
        elif k_lower in ("right", "l"):
            self.app._shift_date(1)
            return
        elif k_lower in ("0", "today"):
            self.app.current_date = datetime.date.today()
            self.app.cal_focus_date = self.app.current_date
            self.app.refresh_data()
            self.app.animate_progress_bar()
            self.app.set_toast(self.app.theme_obj.messages.toast_today)
            return

        # CRUD actions
        elif k_lower == "a":
            self.app.action_add_task()
            return
        elif k_lower in ("e", "r"):
            self.app.action_rename_task()
            return
        elif k_lower in ("d", "x"):
            self.app.action_delete_task()
            return

        # Calendar toggle / theme / quit
        elif k_lower == "c":
            self.app.calendar_active = not getattr(self.app, "calendar_active", False)
            self.app.cal_focus_date = self.app.current_date
            self.app.set_toast(
                self.app.theme_obj.messages.toast_cal_on
                if self.app.calendar_active
                else self.app.theme_obj.messages.toast_cal_off
            )
            self.app._refresh_all_widgets()
            return
        elif k in ("t", "T"):
            self.app.action_cycle_theme()
            return
        elif k_lower == "q":
            self.app.exit()
            return
