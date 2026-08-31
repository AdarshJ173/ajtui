"""
lifeOS Master Application
=========================
Ultra-fast, zero-latency reactive routine tracker with Journal and Cloud Sync.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.stylesheet import CssSource

from lifeos.core.models import Completion, SyncState, SyncStateEnum, Task
from lifeos.db.local import DatabaseManager
from lifeos.db.supabase_sync import SupabaseSyncEngine
from lifeos.ui.journal_screen import JournalScreen
from lifeos.ui.themes import (
    Animator,
    Capabilities,
    Theme,
    ease_out_cubic,
    get_theme,
    resolve_startup_theme,
)
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


class DailyOS(App):
    """lifeOS Daily Tracker & Journal — Master Application."""

    CSS = ""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        journal_dir: Optional[Path] = None,
        theme_name: Optional[str] = None,
    ):
        super().__init__()
        self.caps = Capabilities()

        # Theme persistence
        persisted_theme = os.environ.get("LIFEOS_THEME", "").strip().lower()
        if not theme_name and not persisted_theme:
            cfg_file = Path.home() / ".lifeos" / "theme.cfg"
            if cfg_file.exists():
                try:
                    persisted_theme = cfg_file.read_text().strip().lower()
                except Exception:
                    pass

        self.theme_name = theme_name or persisted_theme or "lifeos"
        self.theme_obj = resolve_startup_theme(self.theme_name, self.caps)
        self.CSS = self.theme_obj.css

        self.db = DatabaseManager(db_path=db_path, journal_dir=journal_dir)
        self.sync_state = SyncState(status=SyncStateEnum.LOCAL_ONLY, message="local-only")

        self.current_date = datetime.date.today()
        self.cal_focus_date = datetime.date.today()
        self.calendar_active = False

        self.tasks: List[Task] = []
        self.completions: Dict[int, Completion] = {}
        self.streak_count: int = 0
        self.month_stats: Dict[str, Tuple[int, int]] = {}
        self.journal_dates_this_month: Set[str] = set()
        self.sparkline_data: List[float] = [0.0] * 7
        self.cursor_idx: int = 0
        self.toast_message: str = ""
        self._toast_timer: Any = None
        self._last_deleted_task_id: Optional[int] = None
        self._last_deleted_task_title: str = ""

        # Fast animation state
        self.anim_progress: float = 0.0
        self.target_progress: float = 0.0
        self.flip_anims: Dict[int, Tuple[int, int, bool]] = {}
        self.cal_slide: Tuple[int, int, int] = (0, 0, 0)
        self.boot_frame: int = 0
        self.booting: bool = not self.caps.reduced_motion
        self.flame_lit: bool = True
        self.now_time_str: str = datetime.datetime.now().strftime("%H:%M:%S")

        self.ui_animator = Animator(self, tick=self.theme_obj.anim.tick)

        # Background cloud sync engine
        self.sync_engine = SupabaseSyncEngine(
            db_manager=self.db,
            on_remote_change=self._on_remote_sync_event,
            on_status_change=self._on_sync_status_event,
            on_conflict=self._on_sync_conflict_event,
        )

    # -- layout & composition --------------------------------------------------

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
        if self.booting:
            with Vertical(id="boot_layer"):
                yield BootOverlay(id="boot")

    def on_mount(self) -> None:
        self.refresh_data()
        self.ui_animator.start()
        self.sync_engine.start()

        self.set_interval(1.0, self._clock_tick)
        if os.environ.get("LIFEOS_AMBIENT") and not self.caps.reduced_motion:
            self.set_interval(self.theme_obj.anim.ambient_period, self._ambient_tick)

        self._apply_layout_mode()
        if self.booting:
            self._start_boot()
        else:
            self.anim_progress = self.target_progress

    def on_unmount(self) -> None:
        self.sync_engine.stop()
        self.ui_animator.stop()

    def _apply_layout_mode(self) -> None:
        try:
            main = self.query_one("#main_content")
            main.set_class(self.size.width < self.theme_obj.metrics.stack_bp, "stacked")
        except Exception:
            pass

    def on_resize(self, event: events.Resize) -> None:
        self._apply_layout_mode()

    # -- Sync callbacks --------------------------------------------------------

    def _on_remote_sync_event(self) -> None:
        if getattr(self, "is_running", False):
            try:
                self.call_from_thread(self.refresh_data)
            except Exception:
                pass

    def _on_sync_status_event(self, state: SyncState) -> None:
        self.sync_state = state
        if getattr(self, "is_running", False):
            try:
                self.call_from_thread(self._refresh_header_status)
            except Exception:
                pass

    def _on_sync_conflict_event(self, date_str: str, backup_path: str) -> None:
        if getattr(self, "is_running", False):
            try:
                self.call_from_thread(
                    self.set_toast,
                    f"Sync conflict on {date_str} — saved loser to {Path(backup_path).name}",
                )
            except Exception:
                pass

    def _refresh_header_status(self) -> None:
        try:
            self.query_one(HeaderBar).refresh()
        except Exception:
            pass

    # -- Clock & ambient -------------------------------------------------------

    def _clock_tick(self) -> None:
        new_time = datetime.datetime.now().strftime("%H:%M:%S")
        if new_time != self.now_time_str:
            self.now_time_str = new_time
            try:
                self.query_one(HeaderBar).refresh()
            except Exception:
                pass

    def _ambient_tick(self) -> None:
        if self.streak_count > 0:
            self.flame_lit = not self.flame_lit
            try:
                self.query_one(HeaderBar).refresh()
            except Exception:
                pass

    # -- Boot sequence ---------------------------------------------------------

    def _start_boot(self) -> None:
        a = self.theme_obj.anim

        def on_frame(f: int):
            self.boot_frame = f
            try:
                self.query_one(BootOverlay).refresh()
            except Exception:
                pass

        def on_done():
            self._end_boot()

        self.ui_animator.play("boot", a.boot_frames, on_frame=on_frame, on_done=on_done)

    def _end_boot(self) -> None:
        self.booting = False
        try:
            for widget in self.query("#boot_layer"):
                widget.remove()
        except Exception:
            pass
        self._refresh_all_widgets()
        self.animate_progress_bar()

    # -- Data refresh ----------------------------------------------------------

    def refresh_data(self) -> None:
        self.tasks = self.db.get_tasks()
        date_str = self.current_date.strftime("%Y-%m-%d")
        self.completions = self.db.get_day_completions(date_str)
        self.streak_count = self.db.calculate_streak(self.current_date)
        self.month_stats = self.db.get_month_completion_stats(
            self.cal_focus_date.year, self.cal_focus_date.month
        )
        self.refresh_journal_markers()
        self.sparkline_data = self.db.get_past_7_days_fractions(self.current_date)

        if self.tasks:
            self.cursor_idx = max(0, min(len(self.tasks) - 1, self.cursor_idx))
        else:
            self.cursor_idx = 0

        total = len(self.tasks)
        done = sum(
            1 for t in self.tasks
            if self.completions.get(t.id, Completion(t.id, "", False)).done
        )
        self.target_progress = (done / total) if total > 0 else 0.0

        if self.caps.reduced_motion or self.booting:
            self.anim_progress = self.target_progress

        self._refresh_all_widgets()

    def refresh_journal_markers(self) -> None:
        start_date = f"{self.cal_focus_date.year:04d}-{self.cal_focus_date.month:02d}-01"
        end_date = f"{self.cal_focus_date.year:04d}-{self.cal_focus_date.month:02d}-31"
        self.journal_dates_this_month = self.db.get_dates_with_journals(start_date, end_date)
        try:
            self.query_one(MonthCalendarView).refresh()
        except Exception:
            pass

    def _refresh_all_widgets(self) -> None:
        if self.booting:
            return
        for cls in (
            HeaderBar, HeroBanner, TaskListView, MonthCalendarView,
            MomentumDock, ToastRail, KeyChipBar,
        ):
            try:
                self.query_one(cls).refresh()
            except Exception:
                pass

    def set_toast(self, message: str, ttl: Optional[float] = None) -> None:
        self.toast_message = message
        try:
            self.query_one(ToastRail).refresh()
        except Exception:
            pass

        if getattr(self, "_toast_timer", None) is not None:
            try:
                self._toast_timer.stop()
            except Exception:
                pass
            self._toast_timer = None

        effective_ttl = ttl if ttl is not None else getattr(self.theme_obj.anim, "toast_ttl", 2.6)
        if effective_ttl > 0 and message:
            try:
                self._toast_timer = self.set_timer(effective_ttl, self._clear_toast)
            except Exception:
                pass

    def _clear_toast(self) -> None:
        self.toast_message = ""
        self._toast_timer = None
        try:
            self.query_one(ToastRail).refresh()
        except Exception:
            pass

    # -- Animations ------------------------------------------------------------

    def animate_progress_bar(self) -> None:
        a = self.theme_obj.anim
        if self.caps.reduced_motion or self.booting:
            self.anim_progress = self.target_progress
            if not self.booting:
                try:
                    self.query_one(MomentumDock).refresh()
                except Exception:
                    pass
            return

        start_val = self.anim_progress
        target_val = self.target_progress
        frames = a.progress_frames

        def on_frame(f: int):
            eased = ease_out_cubic(f / max(1, frames - 1))
            self.anim_progress = start_val + (target_val - start_val) * eased
            try:
                self.query_one(MomentumDock).refresh()
            except Exception:
                pass

        def on_done():
            self.anim_progress = target_val
            try:
                self.query_one(MomentumDock).refresh()
            except Exception:
                pass

        self.ui_animator.play("bar", frames, on_frame=on_frame, on_done=on_done)

    def animate_flip(self, task_id: int, checking: bool) -> None:
        if self.caps.reduced_motion or self.booting:
            return
        a = self.theme_obj.anim
        frames = a.flip_frames
        name = f"flip_{task_id}"

        def on_frame(f: int):
            self.flip_anims[task_id] = (f, frames, checking)
            try:
                self.query_one(TaskListView).refresh()
            except Exception:
                pass

        def on_done():
            self.flip_anims.pop(task_id, None)
            try:
                self.query_one(TaskListView).refresh()
            except Exception:
                pass

        self.ui_animator.play(name, frames, on_frame=on_frame, on_done=on_done)

    def animate_month_slide(self, direction: int) -> None:
        if self.caps.reduced_motion or self.booting:
            return
        frames = 4

        def on_frame(f: int):
            self.cal_slide = (f, frames, direction)
            try:
                self.query_one(MonthCalendarView).refresh()
            except Exception:
                pass

        def on_done():
            self.cal_slide = (0, 0, 0)
            try:
                self.query_one(MonthCalendarView).refresh()
            except Exception:
                pass

        self.ui_animator.play("calslide", frames, on_frame=on_frame, on_done=on_done)

    # -- Date shifts -----------------------------------------------------------

    def _shift_date(self, days: int) -> None:
        old_month = (self.cal_focus_date.year, self.cal_focus_date.month)
        self.current_date += datetime.timedelta(days=days)
        self.cal_focus_date = self.current_date
        self.refresh_data()
        self.animate_progress_bar()
        new_month = (self.cal_focus_date.year, self.cal_focus_date.month)
        if new_month != old_month:
            self.animate_month_slide(1 if days > 0 else -1)
        self.set_toast(self.theme_obj.messages.toast_jumped.format(
            date=self.current_date.strftime("%b %d, %Y")))

    def _move_cal(self, days: int) -> None:
        old_month = (self.cal_focus_date.year, self.cal_focus_date.month)
        self.cal_focus_date += datetime.timedelta(days=days)
        self.month_stats = self.db.get_month_completion_stats(
            self.cal_focus_date.year, self.cal_focus_date.month
        )
        self.refresh_journal_markers()
        new_month = (self.cal_focus_date.year, self.cal_focus_date.month)
        if new_month != old_month:
            self.animate_month_slide(1 if days > 0 else -1)
        try:
            self.query_one(MonthCalendarView).refresh()
        except Exception:
            pass

    # -- Key handling ----------------------------------------------------------

    def on_key(self, event: events.Key) -> None:
        # Boot overlay: any key immediately skips into the app
        if self.booting:
            self.ui_animator.cancel("boot")
            self._end_boot()
            event.stop()
            return

        # If JournalScreen is active on top, let JournalScreen handle all keys
        if getattr(self.screen, "__class__", None).__name__ == "JournalScreen":
            return

        k = event.key
        k_lower = k.lower()

        # Calendar Interactive Mode
        if self.calendar_active:
            if k_lower in ("escape", "c"):
                self.calendar_active = False
                self.cal_focus_date = self.current_date
                self.set_toast(self.theme_obj.messages.toast_cal_off)
                self._refresh_all_widgets()
                return
            elif k_lower in ("left", "h"):
                self._move_cal(-1)
                return
            elif k_lower in ("right", "l"):
                self._move_cal(1)
                return
            elif k_lower in ("up", "k"):
                self._move_cal(-7)
                return
            elif k_lower in ("down", "j"):
                self._move_cal(7)
                return
            elif k in ("space", "enter"):
                self.current_date = self.cal_focus_date
                self.calendar_active = False
                self.refresh_data()
                self.animate_progress_bar()
                self.set_toast(
                    self.theme_obj.messages.toast_jumped.format(
                        date=self.current_date.strftime("%b %d, %Y")
                    )
                )
                return
            elif k_lower in ("0", "today"):
                self.cal_focus_date = datetime.date.today()
                self.current_date = self.cal_focus_date
                self.calendar_active = False
                self.refresh_data()
                self.animate_progress_bar()
                self.set_toast(self.theme_obj.messages.toast_today)
                return
            elif k in ("j", "J", "5"):
                self.action_open_journal()
                return
            elif k in ("s", "S"):
                self.action_force_sync()
                return
            elif k in ("t", "T"):
                self.action_cycle_theme()
                return
            elif k_lower == "q":
                self.exit()
                return

        # Reorder (capital / shift variants / brackets / ctrl-arrows)
        if k in ("shift+k", "ctrl+up", "alt+up", "[", "K"):
            if self.tasks:
                curr = self.tasks[self.cursor_idx]
                self.db.reorder_task(curr.id, -1)
                self.cursor_idx = max(0, self.cursor_idx - 1)
                self.sync_engine.notify_local_mutation()
                self.refresh_data()
                self.set_toast(
                    self.theme_obj.messages.toast_moved.format(
                        dir="up", title=curr.title
                    )
                )
            return

        if k in ("shift+j", "ctrl+down", "alt+down", "]", "J"):
            if self.tasks:
                curr = self.tasks[self.cursor_idx]
                self.db.reorder_task(curr.id, 1)
                self.cursor_idx = min(len(self.tasks) - 1, self.cursor_idx + 1)
                self.sync_engine.notify_local_mutation()
                self.refresh_data()
                self.set_toast(
                    self.theme_obj.messages.toast_moved.format(
                        dir="down", title=curr.title
                    )
                )
            return

        # List navigation
        if k_lower in ("up", "k"):
            if self.tasks:
                self.cursor_idx = (self.cursor_idx - 1) % len(self.tasks)
                try:
                    self.query_one(TaskListView).refresh()
                except Exception:
                    pass
            return
        elif k_lower in ("down",):
            if self.tasks:
                self.cursor_idx = (self.cursor_idx + 1) % len(self.tasks)
                try:
                    self.query_one(TaskListView).refresh()
                except Exception:
                    pass
            return

        # Open Journal
        elif k == "j" or k == "5":
            self.action_open_journal()
            return

        # Toggle completion
        elif k in ("space", "enter"):
            if not self.tasks:
                self.set_toast(self.theme_obj.messages.toast_no_tasks)
            else:
                curr = self.tasks[self.cursor_idx]
                d_str = self.current_date.strftime("%Y-%m-%d")
                new_state = self.db.toggle_completion(curr.id, d_str)
                self.sync_engine.notify_local_mutation()
                self.refresh_data()
                self.animate_flip(curr.id, new_state)
                self.animate_progress_bar()
                msg = self.theme_obj.messages
                self.set_toast(
                    (msg.toast_done if new_state else msg.toast_undone).format(
                        title=curr.title
                    )
                )
            return

        # Date navigation
        elif k_lower in ("left", "h"):
            self._shift_date(-1)
            return
        elif k_lower in ("right", "l"):
            self._shift_date(1)
            return
        elif k_lower in ("0", "today"):
            self.current_date = datetime.date.today()
            self.cal_focus_date = self.current_date
            self.refresh_data()
            self.animate_progress_bar()
            self.set_toast(self.theme_obj.messages.toast_today)
            return

        # CRUD actions
        elif k_lower == "a":
            self.action_add_task()
            return
        elif k_lower in ("e", "r"):
            self.action_rename_task()
            return
        elif k_lower in ("d", "x"):
            self.action_delete_task()
            return
        elif k_lower in ("u", "ctrl+z"):
            self.action_undo_delete()
            return

        # Force sync
        elif k in ("s", "S"):
            self.action_force_sync()
            return

        # Calendar toggle / theme / quit
        elif k_lower == "c":
            self.calendar_active = not self.calendar_active
            self.cal_focus_date = self.current_date
            self.set_toast(
                self.theme_obj.messages.toast_cal_on
                if self.calendar_active
                else self.theme_obj.messages.toast_cal_off
            )
            self._refresh_all_widgets()
            return
        elif k in ("t", "T"):
            self.action_cycle_theme()
            return
        elif k_lower == "q":
            self.exit()
            return

    # -- Actions ---------------------------------------------------------------

    def action_open_journal(self) -> None:
        def on_return(res=None):
            self.refresh_data()
            self._refresh_all_widgets()
        self.push_screen(JournalScreen(), on_return)

    def action_force_sync(self) -> None:
        self.set_toast(self.theme_obj.messages.toast_sync_forced)
        self.sync_engine.trigger_sync()

    def action_add_task(self) -> None:
        def on_submit(title: Optional[str]):
            if title:
                self.db.add_task(title)
                self.cursor_idx = len(self.tasks)
                self.sync_engine.notify_local_mutation()
                self.refresh_data()
                self.animate_progress_bar()
                self.set_toast(self.theme_obj.messages.toast_added)

        self.push_screen(TextInputModal("Enter new daily ritual:"), on_submit)

    def action_rename_task(self) -> None:
        if not self.tasks:
            self.set_toast(self.theme_obj.messages.toast_no_tasks)
            return
        curr = self.tasks[self.cursor_idx]

        def on_submit(title: Optional[str]):
            if title and title != curr.title:
                self.db.update_task_title(curr.id, title)
                self.sync_engine.notify_local_mutation()
                self.refresh_data()
                self.set_toast(self.theme_obj.messages.toast_renamed.format(title=title))

        self.push_screen(
            TextInputModal("Rename daily ritual:", initial=curr.title),
            on_submit,
        )

    def action_delete_task(self) -> None:
        if not self.tasks:
            self.set_toast(self.theme_obj.messages.toast_no_tasks)
            return
        curr = self.tasks[self.cursor_idx]
        self._last_deleted_task_id = curr.id
        self._last_deleted_task_title = curr.title
        self.db.delete_task(curr.id)
        self.cursor_idx = max(0, min(len(self.tasks) - 2, self.cursor_idx))
        self.sync_engine.notify_local_mutation()
        self.refresh_data()
        self.animate_progress_bar()
        self.set_toast(f"Deleted '{curr.title}' · Press U to undo", ttl=5.0)

    def action_undo_delete(self) -> None:
        if self._last_deleted_task_id is not None:
            task_id = self._last_deleted_task_id
            title = self._last_deleted_task_title
            self._last_deleted_task_id = None
            self._last_deleted_task_title = ""
            restored = self.db.restore_task(task_id)
            if restored:
                self.sync_engine.notify_local_mutation()
                self.refresh_data()
                self.cursor_idx = len(self.tasks) - 1
                self.animate_progress_bar()
                self.set_toast(f"Restored '{title}'", ttl=3.0)

    def action_cycle_theme(self) -> None:
        themes = ["lifeos", "phosphor", "amber"]
        next_idx = (themes.index(self.theme_name) + 1) % len(themes) \
            if self.theme_name in themes else 0
        self.theme_name = themes[next_idx]
        self.theme_obj = get_theme(self.theme_name, self.caps)

        try:
            cfg_dir = Path.home() / ".lifeos"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            (cfg_dir / "theme.cfg").write_text(self.theme_name)
        except Exception:
            pass

        for key in list(self.stylesheet.source.keys()):
            if "CSS" in key[1]:
                old_source = self.stylesheet.source[key]
                self.stylesheet.source[key] = CssSource(
                    self.theme_obj.css,
                    old_source.is_defaults,
                    old_source.tie_breaker,
                    old_source.scope,
                )
        self.refresh_css()
        self._apply_layout_mode()
        self._refresh_all_widgets()
        self.set_toast(self.theme_obj.messages.toast_theme.format(
            name=self.theme_obj.label))


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="lifeOS Daily — Ritual & Momentum Terminal App")
    parser.add_argument("--theme", choices=["lifeos", "phosphor", "amber"],
                        default=None, help="Startup visual theme")
    parser.add_argument("--db", type=Path, default=None,
                        help="Custom SQLite database file")
    args = parser.parse_args()

    app = DailyOS(db_path=args.db, theme_name=args.theme)
    app.run()


if __name__ == "__main__":
    main()
