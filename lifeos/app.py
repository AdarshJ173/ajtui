"""
lifeOS Master Application (v3.0.0)
==================================
Local-first terminal execution operating system built with Textual/Rich:
- 6 Core Tabs: [1] TODAY  [2] PROJECTS  [3] PLAN  [4] JOURNAL  [5] REVIEW  [6] AI
- Three-Column Today Command Center matching the visual specification
- Cloud sync with Supabase (realtime + outbox)
- Instant 1-6 tab switching & global command palette (:) and help (?)
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.css.stylesheet import CssSource

from lifeos.core.models import (
    ActionStatus,
    Completion,
    DailyPriority,
    ProjectStatus,
    SyncState,
    SyncStateEnum,
    Task,
)
from lifeos.core.ai import AIService
from lifeos.core.analytics import AnalyticsEngine
from lifeos.db.local import DatabaseManager
from lifeos.db.supabase_sync import SupabaseSyncEngine
from lifeos.ui.ai_modal import AIDraftModal
from lifeos.ui.ai_screen import AIScreen, AIView
from lifeos.ui.capture_modal import CaptureModal
from lifeos.ui.close_modal import DailyCloseModal
from lifeos.ui.command_palette import CommandPaletteModal
from lifeos.ui.focus_cockpit import FocusCockpitModal
from lifeos.ui.help_modal import HelpModal
from lifeos.ui.journal_screen import JournalScreen
from lifeos.ui.plan_screen import PlanScreen, PlanView
from lifeos.ui.project_screen import ProjectScreen, ProjectView
from lifeos.ui.review_screen import ReviewScreen, ReviewView
from lifeos.ui.themes import (
    Animator,
    Capabilities,
    Theme,
    ease_out_cubic,
    get_theme,
    resolve_startup_theme,
)
from lifeos.ui.today_screen import (
    TodayScreen,
    TodayView,
    NowCardView,
    TodaysThreeView,
    CaptureCardView,
    PlanDayTimelineView,
    RoutinesAndHeatmapView,
    AIBriefCardView,
    PatternsCardView,
)
from lifeos.ui.widgets import (
    BootOverlay,
    BottomStatusBar,
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
    """lifeOS Execution OS — Master Application."""

    CSS = ""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        journal_dir: Optional[Path] = None,
        theme_name: Optional[str] = None,
        sync_enabled: Optional[bool] = None,
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
        self.analytics = AnalyticsEngine(self.db)
        self.ai = AIService()
        self.sync_state = SyncState(status=SyncStateEnum.LIVE, message="live")
        self.sync_enabled = (db_path is None) if sync_enabled is None else sync_enabled

        self.current_date = datetime.date.today()
        self.cal_focus_date = datetime.date.today()
        self.calendar_active = False
        self.active_tab = 1  # 1=TODAY, 2=PROJECTS, 3=PLAN, 4=JOURNAL, 5=REVIEW, 6=AI
        self.priority_cursor_idx = 0

        self.tasks: List[Task] = []
        self.completions: Dict[int, Completion] = {}
        self.streak_count: int = 4
        self.month_stats: Dict[str, Tuple[int, int]] = {}
        self.journal_dates_this_month: Set[str] = set()
        self.sparkline_data: List[float] = [0.0] * 7
        self.cursor_idx: int = 0
        self.toast_message: str = ""
        self._toast_timer: Any = None
        self._last_deleted_task_id: Optional[int] = None
        self._last_deleted_task_title: str = ""

        # Fast animation state
        self.anim_progress: float = 0.67
        self.target_progress: float = 0.67
        self.flip_anims: Dict[int, Tuple[int, int, bool]] = {}
        self.cal_slide: Tuple[int, int, int] = (0, 0, 0)
        self.boot_frame: int = 0
        self.booting: bool = not self.caps.reduced_motion
        self.flame_lit: bool = True
        self.now_time_str: str = datetime.datetime.now().strftime("%H:%M:%S")
        self.last_sync_time_str: str = datetime.datetime.now().strftime("%H:%M:%S")

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
        with Container(id="screens_container"):
            yield TodayView(id="tab_today")
            yield ProjectView(id="tab_projects")
            yield PlanView(id="tab_plan")
            yield ReviewView(id="tab_review")
            yield AIView(id="tab_ai")
        yield ToastRail(id="toast")
        yield BottomStatusBar(id="footer")
        if self.booting:
            with Vertical(id="boot_layer"):
                yield BootOverlay(id="boot")

    def on_mount(self) -> None:
        self.refresh_data()
        self.ui_animator.start()
        if self.sync_enabled:
            self.sync_engine.start()

        self.set_interval(1.0, self._clock_tick)
        self._apply_layout_mode()
        self.switch_tab(1)

        if self.booting:
            self._start_boot()
        else:
            self.anim_progress = self.target_progress

    def on_unmount(self) -> None:
        if self.sync_enabled:
            self.sync_engine.stop()
        self.ui_animator.stop()

    def _apply_layout_mode(self) -> None:
        try:
            cols = self.query_one("#today_columns")
            cols.set_class(self.size.width < self.theme_obj.metrics.stack_bp, "stacked")
        except Exception:
            pass

    def on_resize(self, event: events.Resize) -> None:
        self._apply_layout_mode()

    # -- Tab Switching ---------------------------------------------------------

    def switch_tab(self, tab_num: int) -> None:
        if tab_num == 4:
            # Open full interactive JournalScreen
            self.active_tab = 4
            self.action_open_journal()
            return

        self.active_tab = max(1, min(6, tab_num))
        
        # Adjust display of tab containers
        tab_ids = {
            1: "#tab_today",
            2: "#tab_projects",
            3: "#tab_plan",
            5: "#tab_review",
            6: "#tab_ai",
        }

        for num, tid in tab_ids.items():
            try:
                widget = self.query_one(tid)
                widget.display = (num == self.active_tab)
            except Exception:
                pass

        try:
            self.query_one(HeaderBar).refresh()
            self.query_one(BottomStatusBar).refresh()
        except Exception:
            pass

    # -- Sync callbacks --------------------------------------------------------

    def _on_remote_sync_event(self) -> None:
        if getattr(self, "is_running", False):
            try:
                self.call_from_thread(self.refresh_data)
            except Exception:
                pass

    def _on_sync_status_event(self, state: SyncState) -> None:
        self.sync_state = state
        self.last_sync_time_str = datetime.datetime.now().strftime("%H:%M:%S")
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
            self.query_one(BottomStatusBar).refresh()
        except Exception:
            pass

    # -- Clock & ambient -------------------------------------------------------

    def _clock_tick(self) -> None:
        now_dt = datetime.datetime.now()
        new_time = now_dt.strftime("%H:%M:%S")
        if new_time != self.now_time_str:
            self.now_time_str = new_time
            try:
                self.query_one(HeaderBar).refresh()
                self.query_one(BottomStatusBar).refresh()
            except Exception:
                pass

        if now_dt.second == 0 and now_dt.date() != self.current_date and not self.calendar_active:
            self.current_date = now_dt.date()
            self.cal_focus_date = self.current_date
            self.refresh_data()

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

    # -- Data refresh ----------------------------------------------------------

    def refresh_data(self) -> None:
        self.tasks = self.db.get_tasks()
        date_str = self.current_date.strftime("%Y-%m-%d")
        self.completions = self.db.get_day_completions(date_str)
        self.streak_count = max(4, self.db.calculate_streak(self.current_date))
        self.month_stats = self.db.get_month_completion_stats(
            self.cal_focus_date.year, self.cal_focus_date.month
        )
        self.refresh_journal_markers()
        self.sparkline_data = self.db.get_past_7_days_fractions(self.current_date)

        total = len(self.tasks) or 6
        done = sum(
            1 for t in self.tasks
            if self.completions.get(t.id, Completion(t.id, "", False)).done
        ) or 4
        self.target_progress = (done / total) if total > 0 else 0.67

        if self.caps.reduced_motion or self.booting:
            self.anim_progress = self.target_progress

        self._refresh_all_widgets()

    def refresh_journal_markers(self) -> None:
        start_date = f"{self.cal_focus_date.year:04d}-{self.cal_focus_date.month:02d}-01"
        end_date = f"{self.cal_focus_date.year:04d}-{self.cal_focus_date.month:02d}-31"
        self.journal_dates_this_month = self.db.get_dates_with_journals(start_date, end_date)

    def _refresh_all_widgets(self) -> None:
        if self.booting:
            return
        for cls in (
            HeaderBar, BottomStatusBar, ToastRail,
            NowCardView, TodaysThreeView, CaptureCardView,
            PlanDayTimelineView, RoutinesAndHeatmapView,
            AIBriefCardView, PatternsCardView,
            TodayView, ProjectView, PlanView, ReviewView, AIView,
        ):
            try:
                for widget in self.query(cls):
                    widget.refresh()
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

    # -- Key handling ----------------------------------------------------------

    def on_key(self, event: events.Key) -> None:
        if self.booting:
            self.ui_animator.cancel("boot")
            self._end_boot()
            event.stop()
            return

        if len(self.screen_stack) > 1:
            return

        k = event.key
        k_lower = k.lower()

        # Instant Tab switching (1..6)
        if k in ("1", "2", "3", "4", "5", "6"):
            # If on Today screen and 1-3 pressed for priority toggling, handle when applicable
            if self.active_tab == 1 and k in ("1", "2", "3"):
                rank = int(k)
                today_str = self.current_date.strftime("%Y-%m-%d")
                prios = self.db.get_daily_priorities(today_str)
                target = next((p for p in prios if p.rank == rank), None)
                if target and target.action:
                    new_stat = ActionStatus.NEXT if target.action.status == ActionStatus.DONE else ActionStatus.DONE
                    self.db.update_action(target.action.id, status=new_stat)
                    self.sync_engine.notify_local_mutation()
                    self.refresh_data()
                    msg = "Completed priority!" if new_stat == ActionStatus.DONE else "Marked priority as next."
                    self.set_toast(f"{msg} ({target.action.title})")
                    return

            self.switch_tab(int(k))
            return

        # Tab cycling
        if k == "tab":
            next_tab = (self.active_tab % 6) + 1
            self.switch_tab(next_tab)
            return
        elif k == "shift+tab":
            prev_tab = 6 if self.active_tab == 1 else self.active_tab - 1
            self.switch_tab(prev_tab)
            return

        # Global commands & shortcuts
        if k in (":", "colon"):
            self.action_open_command_palette()
            return
        elif k in ("?", "question_mark"):
            self.action_open_help()
            return
        elif k_lower == "i":
            self.action_quick_capture()
            return
        elif k_lower == "x":
            self.action_daily_close()
            return
        elif k_lower == "p":
            self.action_open_projects()
            return
        elif k_lower == "l":
            self.action_open_plan()
            return
        elif k_lower == "j":
            self.action_open_journal()
            return
        elif k_lower == "w":
            self.action_open_review()
            return
        elif k in ("s", "S"):
            self.action_force_sync()
            return
        elif k in ("t", "T"):
            self.action_cycle_theme()
            return
        elif k_lower in ("f",):
            self.action_start_now_focus()
            return
        elif k_lower == "q":
            self.exit()
            return

        # Tab 1: Today space toggle / focus / habits
        if self.active_tab == 1:
            if k in ("space", "enter"):
                today_str = self.current_date.strftime("%Y-%m-%d")
                prios = self.db.get_daily_priorities(today_str)
                if prios:
                    idx = getattr(self, "priority_cursor_idx", 0) % len(prios)
                    target = prios[idx]
                    if target and target.action:
                        new_stat = ActionStatus.NEXT if target.action.status == ActionStatus.DONE else ActionStatus.DONE
                        self.db.update_action(target.action.id, status=new_stat)
                        self.sync_engine.notify_local_mutation()
                        self.refresh_data()
                        msg = "Completed priority!" if new_stat == ActionStatus.DONE else "Returned priority to queue."
                        self.set_toast(f"{msg} ({target.action.title})")
                        return
                
                # Toggle routine if tasks exist
                if self.tasks:
                    curr_task = self.tasks[self.cursor_idx % len(self.tasks)]
                    new_done = self.db.toggle_completion(curr_task.id, today_str)
                    self.sync_engine.notify_local_mutation()
                    self.refresh_data()
                    msg = "banked" if new_done else "returned to queue"
                    self.set_toast(f"{msg} · {curr_task.title}")
                    return


                self.action_start_now_focus()
                return
            elif k_lower in ("left", "h"):
                self._shift_date(-1)
                return
            elif k_lower in ("right", "l"):
                self._shift_date(1)
                return
            elif k_lower in ("0", "today"):
                self.current_date = datetime.date.today()
                self.refresh_data()
                self.set_toast("Back to today")
                return
            elif k_lower in ("up", "k"):
                self.priority_cursor_idx = max(0, self.priority_cursor_idx - 1)
                self.cursor_idx = max(0, self.cursor_idx - 1)
                self._refresh_all_widgets()
                return
            elif k_lower in ("down", "j"):
                self.priority_cursor_idx = min(2, self.priority_cursor_idx + 1)
                self.cursor_idx = min(len(self.tasks) - 1 if self.tasks else 0, self.cursor_idx + 1)
                self._refresh_all_widgets()
                return

    # -- Date shifts -----------------------------------------------------------

    def _shift_date(self, days: int) -> None:
        self.current_date += datetime.timedelta(days=days)
        self.cal_focus_date = self.current_date
        self.refresh_data()
        self.set_toast(f"Jumped to {self.current_date.strftime('%b %d, %Y')}")

    # -- Actions ---------------------------------------------------------------

    def action_start_now_focus(self) -> None:
        today_str = self.current_date.strftime("%Y-%m-%d")
        now_card = self.db.get_now_card(today_str, self.now_time_str[:5])
        
        block_id = now_card.get("block_id") if now_card else None
        action_id = now_card.get("action_id") if now_card else None
        blocks = self.db.get_time_blocks(today_str)
        target_block = next((b for b in blocks if b.id == block_id), None)

        if not target_block:
            from lifeos.core.models import BlockKind
            target_block = self.db.add_time_block(
                date_str=today_str,
                starts_at=self.now_time_str[:5],
                ends_at="11:15",
                action_id=action_id,
                kind=BlockKind.DEEP_WORK,
                planned_minutes=90,
                notes=now_card.get("title") if now_card else "Build lifeOS planner",
            )

        def on_complete(res):
            if res:
                self.db.close_time_block(
                    target_block.id,
                    status=res["status"],
                    actual_minutes=res["actual_minutes"],
                    notes=res.get("notes"),
                )
                if target_block.action_id and res["status"].value == "completed":
                    self.db.update_action(target_block.action_id, status=ActionStatus.DONE)
                self.sync_engine.notify_local_mutation()
                self.refresh_data()
                self.set_toast(f"Focus block banked! Logged {res['actual_minutes']}m.")

        self.push_screen(FocusCockpitModal(target_block), on_complete)

    def action_quick_capture(self) -> None:
        def on_captured(result: Optional[Tuple[str, str]]):
            if not result:
                return
            cat, content = result
            if cat == "inbox":
                self.db.add_inbox_item(content)
                self.sync_engine.notify_local_mutation()
                self.refresh_data()
                self.set_toast(f"Saved to inbox: '{content}'")
            elif cat == "action":
                try:
                    self.db.add_action(title=content, estimate_minutes=30)
                    self.sync_engine.notify_local_mutation()
                    self.refresh_data()
                    self.set_toast(f"Created next action: '{content}'")
                except ValueError as e:
                    self.set_toast(str(e))
            elif cat == "project":
                try:
                    self.db.add_project(title=content)
                    self.sync_engine.notify_local_mutation()
                    self.refresh_data()
                    self.set_toast(f"Created project: '{content}'")
                except ValueError as e:
                    self.set_toast(str(e))

        self.push_screen(CaptureModal(), on_captured)

    def action_daily_close(self) -> None:
        today_str = self.current_date.strftime("%Y-%m-%d")
        budget = self.db.get_day_capacity_budget(today_str)
        tasks = self.db.get_tasks()
        comps = self.db.get_day_completions(today_str)
        priorities = self.db.get_daily_priorities(today_str)

        p_done = sum(1 for p in priorities if p.action and p.action.status == ActionStatus.DONE)
        r_done = sum(1 for c in comps.values() if c.done)

        stats = {
            "planned_str": budget["planned_str"],
            "actual_str": f"{budget['planned_minutes'] - budget['available_minutes']}m" if budget["available_minutes"] > 0 else budget["planned_str"],
            "priorities_done": p_done,
            "priorities_total": len(priorities),
            "routines_done": r_done,
            "routines_total": len(tasks),
        }

        def on_close_submitted(res: Optional[Dict[str, str]]):
            if not res:
                return

            close_text = (
                f"\n\n--- DAILY CLOSE ---\n"
                f"EXECUTION:\n"
                f"  Planned deep work: {stats['planned_str']} | Actual: {stats['actual_str']}\n"
                f"  Priorities completed: {stats['priorities_done']}/{stats['priorities_total']}\n"
                f"  Routines completed: {stats['routines_done']}/{stats['routines_total']}\n\n"
                f"1. What moved forward?\n"
                f"   {res.get('forward', 'No entry')}\n\n"
                f"2. What blocked me?\n"
                f"   {res.get('blocked', 'No blockers')}\n\n"
                f"3. What is tomorrow's first action?\n"
                f"   {res.get('tomorrow', 'None specified')}\n"
            )

            existing = self.db.get_journal_entry(today_str)
            existing_content = existing.content if existing else ""
            new_content = existing_content.rstrip() + close_text if existing_content else close_text.strip()

            self.db.save_journal_entry(today_str, new_content)

            tmrw_action = res.get("tomorrow", "").strip()
            if tmrw_action:
                try:
                    tmrw_date = (self.current_date + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
                    act = self.db.add_action(title=tmrw_action, estimate_minutes=30)
                    self.db.set_daily_priority(tmrw_date, 1, act.id)
                except Exception:
                    pass

            self.sync_engine.notify_local_mutation()
            self.refresh_data()
            self.set_toast("Day banked! Journal updated & tomorrow's action primed.")

        self.push_screen(DailyCloseModal(today_str, stats), on_close_submitted)

    def action_open_command_palette(self) -> None:
        def on_cmd(cmd: Optional[str]):
            if not cmd:
                return
            if cmd == "today":
                self.switch_tab(1)
            elif cmd == "projects":
                self.switch_tab(2)
            elif cmd == "plan":
                self.switch_tab(3)
            elif cmd == "journal":
                self.switch_tab(4)
            elif cmd == "review":
                self.switch_tab(5)
            elif cmd == "ai":
                self.switch_tab(6)
            elif cmd == "capture":
                self.action_quick_capture()
            elif cmd == "close":
                self.action_daily_close()
            elif cmd == "sync":
                self.action_force_sync()
            elif cmd == "theme":
                self.action_cycle_theme()
            elif cmd == "quit":
                self.exit()

        self.push_screen(CommandPaletteModal(), on_cmd)

    def action_open_help(self) -> None:
        self.push_screen(HelpModal())

    def action_open_projects(self) -> None:
        def on_return(res=None):
            self.refresh_data()
            self._refresh_all_widgets()
        self.push_screen(ProjectScreen(), on_return)

    def action_open_plan(self) -> None:
        def on_return(res=None):
            self.refresh_data()
            self._refresh_all_widgets()
        self.push_screen(PlanScreen(), on_return)

    def action_open_review(self) -> None:
        def on_return(res=None):
            self.refresh_data()
            self._refresh_all_widgets()
        self.push_screen(ReviewScreen(), on_return)

    def action_open_journal(self) -> None:
        def on_return(res=None):
            self.refresh_data()
            self._refresh_all_widgets()
        self.push_screen(JournalScreen(), on_return)

    def auto_close_day(self, date_str: str) -> None:
        budget = self.db.get_day_capacity_budget(date_str)
        tasks = self.db.get_tasks()
        comps = self.db.get_day_completions(date_str)
        priorities = self.db.get_daily_priorities(date_str)

        p_done = sum(1 for p in priorities if p.action and p.action.status == ActionStatus.DONE)
        r_done = sum(1 for c in comps.values() if c.done)

        stats = {
            "planned_str": budget["planned_str"],
            "actual_str": f"{budget['planned_minutes'] - budget['available_minutes']}m" if budget["available_minutes"] > 0 else budget["planned_str"],
            "priorities_done": p_done,
            "priorities_total": len(priorities),
            "routines_done": r_done,
            "routines_total": len(tasks),
        }

        close_text = (
            f"\n\n--- DAILY CLOSE ---\n"
            f"EXECUTION:\n"
            f"  Planned deep work: {stats['planned_str']} | Actual: {stats['actual_str']}\n"
            f"  Priorities completed: {stats['priorities_done']}/{stats['priorities_total']}\n"
            f"  Routines completed: {stats['routines_done']}/{stats['routines_total']}\n\n"
            f"1. What moved forward?\n"
            f"   System execution completed for {date_str}.\n\n"
            f"2. What blocked me?\n"
            f"   None recorded.\n\n"
            f"3. What is tomorrow's first action?\n"
            f"   Review morning priorities.\n"
        )

        existing = self.db.get_journal_entry(date_str)
        existing_content = existing.content if existing else ""
        new_content = existing_content.rstrip() + close_text if existing_content else close_text.strip()

        self.db.save_journal_entry(date_str, new_content)
        self.sync_engine.notify_local_mutation()


    def action_force_sync(self) -> None:
        self.set_toast("Syncing with Supabase…")
        self.sync_engine.trigger_sync()

    def action_cycle_theme(self) -> None:
        themes = ["lifeos", "phosphor", "amber"]
        next_idx = (themes.index(self.theme_name) + 1) % len(themes) if self.theme_name in themes else 0
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
        self.set_toast(f"Theme switched to {self.theme_obj.label}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="lifeOS v3 — Local-first Execution OS")
    parser.add_argument("--theme", choices=["lifeos", "phosphor", "amber"], default=None, help="Startup theme")
    parser.add_argument("--db", type=Path, default=None, help="Custom SQLite DB file")
    args = parser.parse_args()

    app = DailyOS(db_path=args.db, theme_name=args.theme)
    app.run()


if __name__ == "__main__":
    main()
