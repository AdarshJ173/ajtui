#!/usr/bin/env python3
"""
lifeOS Daily — State of the Art Routine & Momentum Tracker
==========================================================
Engineered terminal interface powered by Textual and rich typography.
"""

from __future__ import annotations

import calendar
import datetime
import math
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.css.stylesheet import CssSource
from textual.screen import ModalScreen, Screen
from textual.widgets import Input, Label, Static

from lifeos_theme import (
    Animator,
    Capabilities,
    Theme,
    blank_canvas,
    blit,
    canvas_text,
    ease_out_cubic,
    get_theme,
    resolve_startup_theme,
    sparkline,
)


# ===========================================================================
# Domain Models & SQLite Persistence Layer
# ===========================================================================

@dataclass
class Task:
    id: int
    title: str
    sort_order: int
    created_at: str = ""


@dataclass
class Completion:
    task_id: int
    date: str
    done: bool


DEFAULT_ROUTINES = [
    "Morning sunlight + Hydration (500ml)",
    "Deep focus session (90 mins)",
    "Zone 2 Cardio or Strength workout",
    "Read 15 pages of non-fiction",
    "Nightly shutdown & tomorrow plan",
]


class DatabaseManager:
    """Byte-identical SQLite storage schema at ~/.lifeos/daily.db."""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            config_dir = Path.home() / ".lifeos"
            config_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = config_dir / "daily.db"
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS completions (
                    task_id INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (task_id, date),
                    FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE
                )
                """
            )
            cur = conn.execute("SELECT COUNT(*) FROM tasks")
            if cur.fetchone()[0] == 0:
                for idx, title in enumerate(DEFAULT_ROUTINES):
                    conn.execute(
                        "INSERT INTO tasks (title, sort_order) VALUES (?, ?)",
                        (title, idx),
                    )
            conn.commit()

    def get_tasks(self) -> List[Task]:
        with self._get_conn() as conn:
            cur = conn.execute(
                "SELECT id, title, sort_order, created_at FROM tasks ORDER BY sort_order ASC, id ASC"
            )
            return [
                Task(
                    id=row["id"],
                    title=row["title"],
                    sort_order=row["sort_order"],
                    created_at=str(row["created_at"]),
                )
                for row in cur.fetchall()
            ]

    def add_task(self, title: str) -> Task:
        title = title.strip()
        if not title:
            title = "Untitled Routine"
        with self._get_conn() as conn:
            cur = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM tasks")
            next_order = cur.fetchone()[0]
            cur = conn.execute(
                "INSERT INTO tasks (title, sort_order) VALUES (?, ?)",
                (title, next_order),
            )
            conn.commit()
            task_id = cur.lastrowid
            return Task(id=task_id, title=title, sort_order=next_order)

    def update_task_title(self, task_id: int, title: str) -> None:
        title = title.strip()
        if not title:
            return
        with self._get_conn() as conn:
            conn.execute("UPDATE tasks SET title = ? WHERE id = ?", (title, task_id))
            conn.commit()

    def delete_task(self, task_id: int) -> None:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM completions WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            # Normalize sort order
            cur = conn.execute("SELECT id FROM tasks ORDER BY sort_order ASC, id ASC")
            rows = cur.fetchall()
            for idx, r in enumerate(rows):
                conn.execute("UPDATE tasks SET sort_order = ? WHERE id = ?", (idx, r["id"]))
            conn.commit()

    def reorder_task(self, task_id: int, direction: int) -> None:
        tasks = self.get_tasks()
        idx = next((i for i, t in enumerate(tasks) if t.id == task_id), None)
        if idx is None:
            return
        target_idx = idx + direction
        if 0 <= target_idx < len(tasks):
            tasks[idx], tasks[target_idx] = tasks[target_idx], tasks[idx]
            with self._get_conn() as conn:
                for i, t in enumerate(tasks):
                    conn.execute("UPDATE tasks SET sort_order = ? WHERE id = ?", (i, t.id))
                conn.commit()

    def get_day_completions(self, date_str: str) -> Dict[int, Completion]:
        with self._get_conn() as conn:
            cur = conn.execute(
                "SELECT task_id, date, done FROM completions WHERE date = ?",
                (date_str,),
            )
            return {
                row["task_id"]: Completion(
                    task_id=row["task_id"],
                    date=row["date"],
                    done=bool(row["done"]),
                )
                for row in cur.fetchall()
            }

    def toggle_completion(self, task_id: int, date_str: str) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute(
                "SELECT done FROM completions WHERE task_id = ? AND date = ?",
                (task_id, date_str),
            )
            row = cur.fetchone()
            new_state = 1
            if row is not None:
                new_state = 0 if row["done"] else 1
                conn.execute(
                    "UPDATE completions SET done = ? WHERE task_id = ? AND date = ?",
                    (new_state, task_id, date_str),
                )
            else:
                conn.execute(
                    "INSERT INTO completions (task_id, date, done) VALUES (?, ?, 1)",
                    (task_id, date_str),
                )
            conn.commit()
            return bool(new_state)

    def calculate_streak(self, as_of_date: Optional[datetime.date] = None) -> int:
        if as_of_date is None:
            as_of_date = datetime.date.today()

        tasks = self.get_tasks()
        if not tasks:
            return 0
        total_tasks = len(tasks)

        def is_day_complete(d: datetime.date) -> bool:
            ds = d.strftime("%Y-%m-%d")
            comps = self.get_day_completions(ds)
            completed_count = sum(1 for t in tasks if comps.get(t.id, Completion(t.id, ds, False)).done)
            return completed_count >= total_tasks

        streak = 0
        cur_day = as_of_date

        if is_day_complete(cur_day):
            streak += 1
            cur_day -= datetime.timedelta(days=1)
        else:
            # If today is not done yet, check if yesterday was done to preserve streak
            cur_day -= datetime.timedelta(days=1)

        while is_day_complete(cur_day):
            streak += 1
            cur_day -= datetime.timedelta(days=1)

        return streak

    def get_month_completion_stats(self, year: int, month: int) -> Dict[str, Tuple[int, int]]:
        tasks = self.get_tasks()
        total_tasks = len(tasks)
        if total_tasks == 0:
            return {}

        start_date = datetime.date(year, month, 1)
        _, num_days = calendar.monthrange(year, month)
        end_date = datetime.date(year, month, num_days)

        stats: Dict[str, Tuple[int, int]] = {}
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                SELECT date, SUM(done) as done_count
                FROM completions
                WHERE date >= ? AND date <= ?
                GROUP BY date
                """,
                (start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")),
            )
            done_map = {row["date"]: row["done_count"] for row in cur.fetchall()}

        for day in range(1, num_days + 1):
            d_str = datetime.date(year, month, day).strftime("%Y-%m-%d")
            done_count = done_map.get(d_str, 0)
            stats[d_str] = (min(done_count, total_tasks), total_tasks)

        return stats

    def get_past_7_days_fractions(self, current_date: datetime.date) -> List[float]:
        tasks = self.get_tasks()
        total = len(tasks)
        if total == 0:
            return [0.0] * 7
        fractions = []
        for i in range(6, -1, -1):
            day = current_date - datetime.timedelta(days=i)
            day_str = day.strftime("%Y-%m-%d")
            comps = self.get_day_completions(day_str)
            done = sum(1 for t in tasks if comps.get(t.id, Completion(t.id, day_str, False)).done)
            fractions.append(done / total)
        return fractions


# ===========================================================================
# Custom Crafted UI Components
# ===========================================================================

class KeyChipBar(Static):
    """Refined keyboard shortcuts hint bar styled as chips."""

    def render(self) -> Text:
        th: Theme = self.app.theme_obj
        p = th.palette
        g = th.glyphs

        chips = [
            ("↵", "Toggle"),
            ("A", "Add"),
            ("E", "Rename"),
            ("D", "Delete"),
            ("K/J", "Move"),
            ("←/→", "Date"),
            ("C", "Calendar"),
            ("T", "Theme"),
            ("Q", "Quit"),
        ]

        t = Text()
        t.append(f" {g.squared} ", style=f"{p.accent}")

        for i, (key, label) in enumerate(chips):
            t.append("[", style=f"{p.line}")
            t.append(key, style=f"bold {p.accent_hi}")
            t.append("] ", style=f"{p.line}")
            t.append(label, style=f"{p.text_dim}")
            if i < len(chips) - 1:
                t.append("  ", style=f"{p.line_soft}")

        return t


class HeaderBar(Static):
    """Header element: ASCII mark, viewed date, streak, and real-time clock."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs

        w = self.size.width if self.size.width > 20 else 80
        t = Text()

        # Logo mark
        t.append(f"{g.logo} ", style=f"bold {p.accent_hi}")
        t.append("lifeOS", style=f"bold {p.text_hi}")
        t.append(" DAILY ", style=f"bold {p.accent}")
        t.append(f"{g.line_v} ", style=f"{p.line}")

        # Date string
        view_date = app.current_date
        is_today = view_date == datetime.date.today()
        date_str = view_date.strftime("%A, %b %d, %Y")
        tag = "TODAY" if is_today else ("PAST" if view_date < datetime.date.today() else "FUTURE")
        tag_color = p.state_ok if is_today else (p.text_dim if view_date < datetime.date.today() else p.state_warn)

        t.append(date_str, style=f"bold {p.text_hi}")
        t.append(f" [{tag}] ", style=f"bold {tag_color}")

        # Right side: Streak + Clock
        streak_val = app.streak_count
        flame_color = p.hot if streak_val > 0 else p.text_faint
        now_time = datetime.datetime.now().strftime("%H:%M:%S")

        right_side = Text()
        right_side.append(f"{g.flame} ", style=f"bold {flame_color}")
        right_side.append(f"{streak_val}d streak", style=f"bold {p.hot if streak_val > 0 else p.text_dim}")
        right_side.append(f"  {g.line_v}  ", style=f"{p.line}")
        right_side.append(now_time, style=f"bold {p.text_hi}")

        left_len = len(t.plain)
        right_len = len(right_side.plain)
        pad = max(2, w - left_len - right_len - 2)

        t.append(" " * pad)
        t.append_text(right_side)

        return t


class HeroBanner(Static):
    """Displays contextual status quote and identity."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs

        view_date = app.current_date
        today = datetime.date.today()
        tasks = app.tasks
        comps = app.completions
        total = len(tasks)
        done = sum(1 for t in tasks if comps.get(t.id, Completion(t.id, "", False)).done)

        if view_date > today:
            msg = th.messages.hero_future
            sub = "Plan your intentions ahead. Read-only preview."
            color = p.state_warn
        elif view_date < today:
            msg = th.messages.hero_history
            pct = int((done / total * 100)) if total else 0
            sub = f"Record archived. Completed {done}/{total} routines ({pct}%)."
            color = p.text_dim
        else:
            if total == 0:
                msg = th.messages.momentum_start
                sub = "Press [A] to register your foundational daily habits."
                color = p.accent
            elif done == total:
                msg = th.messages.hero_done
                sub = "All daily rituals completed. Full discipline achieved today."
                color = p.state_ok
            elif done == 0:
                msg = th.messages.hero_today
                sub = f"{total} rituals waiting. First step sets the momentum."
                color = p.accent
            else:
                msg = th.messages.hero_press_on
                sub = f"{done} of {total} completed. Finish the remaining {total - done} to secure the day."
                color = p.accent_hi

        t = Text()
        t.append(f" {g.spark} ", style=f"bold {color}")
        t.append(f"{msg}\n", style=f"bold {p.text_hi}")
        t.append(f"   {sub}", style=f"{p.text_dim}")
        return t


class TaskListView(Static):
    """Routine task items with interactive cursor and micro-animations."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs

        tasks = app.tasks
        comps = app.completions
        cursor = app.cursor_idx
        w = max(40, self.size.width - 2)

        if not tasks:
            t = Text()
            t.append("\n  No active routines.\n", style=f"bold {p.text_dim}")
            t.append(f"  {g.spark} {th.messages.empty_invite} [A]\n", style=f"{p.accent}")
            return t

        t = Text()
        for idx, task in enumerate(tasks):
            is_selected = (idx == cursor)
            is_done = comps.get(task.id, Completion(task.id, "", False)).done

            # Prefix indicator
            if is_selected:
                prefix = f" {g.w_right} "
                prefix_style = f"bold {p.accent_hi}"
                bg_style = f"on {p.band_hot}" if p.band_hot and th.caps.colorful else ""
            else:
                prefix = "   "
                prefix_style = f"{p.text_faint}"
                bg_style = ""

            # Checkbox
            if is_done:
                check_icon = f"[{g.check}]"
                check_style = f"bold {p.state_ok}"
                title_style = f"{p.text_dim}"
            else:
                check_icon = f"[{g.open_box}]"
                check_style = f"bold {p.accent}" if is_selected else f"{p.text_faint}"
                title_style = f"bold {p.text_hi}" if is_selected else f"{p.text}"

            # Flash animation if recently toggled
            if app.flash_task_id == task.id:
                check_icon = f"[{g.check_flash}]"
                check_style = f"bold {p.accent_hi}"
                title_style = f"bold {p.accent_hi}"

            line = Text()
            line.append(prefix, style=prefix_style)
            line.append(check_icon, style=check_style)
            line.append(" ")
            line.append(f"{idx + 1:2d}. ", style=f"{p.text_faint}")
            line.append(task.title, style=title_style)

            # Pad remaining row width
            plain_len = len(line.plain)
            if plain_len < w:
                line.append(" " * (w - plain_len))

            if bg_style:
                line.stylize(bg_style)

            t.append_text(line)
            t.append("\n")

        return t


class MonthCalendarView(Static):
    """Compact month calendar with historical completion semaphores."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs

        cal_date = app.cal_focus_date
        year, month = cal_date.year, cal_date.month
        month_name = calendar.month_name[month]
        stats = app.month_stats

        t = Text()
        # Header
        t.append(f"  {g.spark} {month_name} {year}\n", style=f"bold {p.accent_hi}")
        t.append("  Mo  Tu  We  Th  Fr  Sa  Su\n", style=f"{p.text_faint}")

        month_matrix = calendar.monthcalendar(year, month)
        today = datetime.date.today()
        current = app.current_date

        for week in month_matrix:
            row = Text("  ")
            for day in week:
                if day == 0:
                    row.append("    ")
                else:
                    d_obj = datetime.date(year, month, day)
                    d_str = d_obj.strftime("%Y-%m-%d")
                    done_c, total_c = stats.get(d_str, (0, 0))

                    if total_c > 0 and done_c >= total_c:
                        marker = g.done
                        marker_color = p.state_ok
                    elif done_c > 0:
                        marker = g.partial
                        marker_color = p.state_warn
                    else:
                        marker = " "
                        marker_color = p.text_faint

                    day_str = f"{day:2d}"
                    is_viewed = (d_obj == current)
                    is_real_today = (d_obj == today)

                    if is_viewed:
                        row.append(day_str, style=f"bold {p.on_accent} on {p.accent}")
                    elif is_real_today:
                        row.append(day_str, style=f"bold underline {p.accent_hi}")
                    else:
                        row.append(day_str, style=f"{p.text}")

                    row.append(marker, style=f"bold {marker_color}")
                    row.append(" ")
            t.append_text(row)
            t.append("\n")

        # Legend
        t.append("\n  ", style="")
        t.append(f"{g.done} Complete  ", style=f"{p.state_ok}")
        t.append(f"{g.partial} Partial  ", style=f"{p.state_warn}")
        t.append(f"{g.empty} None", style=f"{p.text_faint}")
        return t


class MomentumDock(Static):
    """Data-viz dock: Animated Braille/Segmented progress bar and sparkline."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs

        tasks = app.tasks
        comps = app.completions
        total = len(tasks)
        done = sum(1 for t in tasks if comps.get(t.id, Completion(t.id, "", False)).done)
        target_fraction = (done / total) if total > 0 else 0.0

        current_anim_fraction = app.anim_progress
        w = max(20, self.size.width - 24)

        # 7-day sparkline
        spark_vals = app.sparkline_data
        spark_chars = sparkline(g, spark_vals)
        spark_str = "".join(spark_chars)

        # Build Progress Bar
        fill_width = int(round(current_anim_fraction * w))
        fill_width = max(0, min(w, fill_width))
        empty_width = max(0, w - fill_width)

        bar_body = g.bar_full * fill_width
        empty_body = g.bar_track * empty_width

        pct_num = int(round(current_anim_fraction * 100))

        t = Text()
        # Line 1: Header + Sparkline
        t.append(f" {g.bolt} MOMENTUM ", style=f"bold {p.accent}")
        t.append(f"{done}/{total} Complete ({pct_num}%)", style=f"bold {p.text_hi}")
        t.append(f"    7D TREND: ", style=f"{p.text_faint}")
        t.append(f"[{spark_str}]", style=f"bold {p.state_ok}")
        t.append("\n")

        # Line 2: The Visual Bar
        t.append(" ", style="")
        t.append(g.bar_left, style=f"bold {p.accent}")
        t.append(bar_body, style=f"bold {p.accent}")
        t.append(empty_body, style=f"{p.line}")
        t.append(f" {pct_num:>3d}%\n", style=f"bold {p.accent_hi}")

        # Line 3: Dynamic Micro-copy
        if total == 0:
            m_copy = th.messages.momentum_start
        elif done == total:
            m_copy = th.messages.momentum_done
        elif done == total - 1:
            m_copy = th.messages.momentum_final
        elif done == 0:
            m_copy = th.messages.momentum_start
        elif done == 1:
            m_copy = th.messages.momentum_open
        elif done >= total // 2:
            m_copy = th.messages.momentum_close.format(n=total - done)
        else:
            m_copy = th.messages.momentum_mid

        t.append(f"  {g.spark} {m_copy}", style=f"{p.text_dim}")

        return t


class ToastRail(Static):
    """Dynamic ephemeral feedback message."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs

        msg = app.toast_message
        if not msg:
            return Text()
        t = Text()
        t.append(f" {g.spark} ", style=f"bold {p.accent_hi}")
        t.append(msg, style=f"bold {p.text_hi}")
        return t


# ===========================================================================
# Modals for Routine Add / Rename
# ===========================================================================

class TextInputModal(ModalScreen[Optional[str]]):
    """Clean minimal modal for Add/Edit operations."""

    DEFAULT_CSS = """
    TextInputModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #modal_box {
        width: 60;
        height: auto;
        padding: 1 2;
        border: round cyan;
        background: #0F141D;
    }
    #modal_prompt {
        margin-bottom: 1;
        color: #F2F7FC;
        text-style: bold;
    }
    #modal_input {
        width: 100%;
        border: tall #1C2634;
        background: #0A0D13;
        color: #F2F7FC;
    }
    #modal_input:focus {
        border: tall #22D3EE;
    }
    """

    def __init__(self, prompt: str, initial: str = ""):
        super().__init__()
        self.prompt_text = prompt
        self.initial_text = initial

    def compose(self) -> ComposeResult:
        with Vertical(id="modal_box"):
            yield Label(self.prompt_text, id="modal_prompt")
            yield Input(value=self.initial_text, id="modal_input")

    def on_mount(self) -> None:
        inp = self.query_one(Input)
        inp.focus()

    @on(Input.Submitted, "#modal_input")
    def on_submit(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)


# ===========================================================================
# The Main Textual Application
# ===========================================================================

class DailyOS(App):
    """lifeOS Daily Tracker — Master Application."""

    CSS = ""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        theme_name: Optional[str] = None,
    ):
        super().__init__()
        self.caps = Capabilities()
        self.theme_name = theme_name or "lifeos"
        self.theme_obj = resolve_startup_theme(self.theme_name, self.caps)
        self.CSS = self.theme_obj.css

        self.db = DatabaseManager(db_path)
        self.current_date = datetime.date.today()
        self.cal_focus_date = datetime.date.today()

        self.tasks: List[Task] = []
        self.completions: Dict[int, Completion] = {}
        self.streak_count: int = 0
        self.month_stats: Dict[str, Tuple[int, int]] = {}
        self.sparkline_data: List[float] = [0.0] * 7

        self.cursor_idx: int = 0
        self.toast_message: str = ""
        self.toast_timer = None

        self.anim_progress: float = 0.0
        self.target_progress: float = 0.0
        self.flash_task_id: Optional[int] = None

        self.ui_animator = Animator(self, tick=0.033)

    def get_css(self) -> str:
        return self.theme_obj.css

    def compose(self) -> ComposeResult:
        with Vertical():
            yield HeaderBar(id="topbar")
            yield HeroBanner(id="hero_panel")
            with Horizontal(id="main_content"):
                yield TaskListView(id="routine_list")
                with Vertical(id="calendar_container"):
                    yield MonthCalendarView(id="cal_panel")
            yield MomentumDock(id="dock_panel")
            yield ToastRail(id="toast")
            yield KeyChipBar(id="footer")

    def on_mount(self) -> None:
        self.refresh_data()
        self.ui_animator.start()
        # Set real-time clock tick
        self.set_interval(1.0, self._clock_tick)
        # Start smooth progress animation
        self.animate_progress_bar()

    def _clock_tick(self) -> None:
        try:
            self.query_one(HeaderBar).refresh()
        except Exception:
            pass

    def refresh_data(self) -> None:
        self.tasks = self.db.get_tasks()
        date_str = self.current_date.strftime("%Y-%m-%d")
        self.completions = self.db.get_day_completions(date_str)
        self.streak_count = self.db.calculate_streak(self.current_date)
        self.month_stats = self.db.get_month_completion_stats(
            self.cal_focus_date.year, self.cal_focus_date.month
        )
        self.sparkline_data = self.db.get_past_7_days_fractions(self.current_date)

        if self.tasks:
            self.cursor_idx = max(0, min(len(self.tasks) - 1, self.cursor_idx))
        else:
            self.cursor_idx = 0

        # Update target progress
        total = len(self.tasks)
        done = sum(1 for t in self.tasks if self.completions.get(t.id, Completion(t.id, "", False)).done)
        self.target_progress = (done / total) if total > 0 else 0.0

        if self.caps.reduced_motion:
            self.anim_progress = self.target_progress

        self._refresh_all_widgets()

    def _refresh_all_widgets(self) -> None:
        for selector in [HeaderBar, HeroBanner, TaskListView, MonthCalendarView, MomentumDock, ToastRail]:
            try:
                self.query_one(selector).refresh()
            except Exception:
                pass

    def set_toast(self, message: str) -> None:
        self.toast_message = message
        try:
            self.query_one(ToastRail).refresh()
        except Exception:
            pass

    def animate_progress_bar(self) -> None:
        if self.caps.reduced_motion:
            self.anim_progress = self.target_progress
            try:
                self.query_one(MomentumDock).refresh()
            except Exception:
                pass
            return

        start_val = self.anim_progress
        target_val = self.target_progress

        def on_frame(f: int):
            t = f / 18.0
            eased = ease_out_cubic(t)
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

        self.ui_animator.play("bar_anim", 18, on_frame=on_frame, on_done=on_done)

    # -----------------------------------------------------------------------
    # Keyboard Navigation and CRUD Actions
    # -----------------------------------------------------------------------

    def on_key(self, event: events.Key) -> None:
        k = event.key.lower()

        # Navigation: Routine list
        if k in ("up", "k"):
            if self.tasks:
                self.cursor_idx = (self.cursor_idx - 1) % len(self.tasks)
                self.query_one(TaskListView).refresh()
        elif k in ("down", "j"):
            if self.tasks:
                self.cursor_idx = (self.cursor_idx + 1) % len(self.tasks)
                self.query_one(TaskListView).refresh()

        # Toggle completion
        elif event.key in ("space", "enter"):
            if self.tasks:
                curr_task = self.tasks[self.cursor_idx]
                d_str = self.current_date.strftime("%Y-%m-%d")
                new_state = self.db.toggle_completion(curr_task.id, d_str)
                self.flash_task_id = curr_task.id
                self.refresh_data()
                self.animate_progress_bar()
                self.set_toast(f"Routine '{curr_task.title}' {'completed!' if new_state else 'unmarked.'}")
                self.set_timer(0.3, self._clear_flash)

        # Date switching
        elif k in ("left", "h"):
            self.current_date -= datetime.timedelta(days=1)
            self.cal_focus_date = self.current_date
            self.refresh_data()
            self.animate_progress_bar()
            self.set_toast(f"Jumped to {self.current_date.strftime('%b %d, %Y')}")
        elif k in ("right", "l"):
            self.current_date += datetime.timedelta(days=1)
            self.cal_focus_date = self.current_date
            self.refresh_data()
            self.animate_progress_bar()
            self.set_toast(f"Jumped to {self.current_date.strftime('%b %d, %Y')}")
        elif k in ("0", "today"):
            self.current_date = datetime.date.today()
            self.cal_focus_date = self.current_date
            self.refresh_data()
            self.animate_progress_bar()
            self.set_toast("Returned to today")

        # Reordering tasks
        elif event.key in ("K", "["):
            if self.tasks:
                curr_task = self.tasks[self.cursor_idx]
                self.db.reorder_task(curr_task.id, -1)
                self.cursor_idx = max(0, self.cursor_idx - 1)
                self.refresh_data()
        elif event.key in ("J", "]"):
            if self.tasks:
                curr_task = self.tasks[self.cursor_idx]
                self.db.reorder_task(curr_task.id, 1)
                self.cursor_idx = min(len(self.tasks) - 1, self.cursor_idx + 1)
                self.refresh_data()

        # Add task
        elif k == "a":
            self.action_add_task()

        # Rename task
        elif k in ("e", "r"):
            self.action_rename_task()

        # Delete task
        elif k in ("d", "x"):
            self.action_delete_task()

        # Cycle theme
        elif event.key == "t" or event.key == "T":
            self.action_cycle_theme()

        # Toggle calendar view
        elif k == "c":
            cal_container = self.query_one("#calendar_container")
            cal_container.toggle_class("hidden")

        # Quit
        elif k == "q":
            self.exit()

    def _clear_flash(self) -> None:
        self.flash_task_id = None
        try:
            self.query_one(TaskListView).refresh()
        except Exception:
            pass

    def action_add_task(self) -> None:
        def on_submit(title: Optional[str]):
            if title:
                new_task = self.db.add_task(title)
                self.cursor_idx = len(self.tasks)
                self.refresh_data()
                self.animate_progress_bar()
                self.set_toast(f"Added routine: '{title}'")

        self.push_screen(TextInputModal("Enter new daily ritual:"), on_submit)

    def action_rename_task(self) -> None:
        if not self.tasks:
            return
        curr_task = self.tasks[self.cursor_idx]

        def on_submit(title: Optional[str]):
            if title and title != curr_task.title:
                self.db.update_task_title(curr_task.id, title)
                self.refresh_data()
                self.set_toast(f"Renamed ritual to: '{title}'")

        self.push_screen(
            TextInputModal("Rename daily ritual:", initial=curr_task.title),
            on_submit,
        )

    def action_delete_task(self) -> None:
        if not self.tasks:
            return
        curr_task = self.tasks[self.cursor_idx]
        self.db.delete_task(curr_task.id)
        self.cursor_idx = max(0, min(len(self.tasks) - 2, self.cursor_idx))
        self.refresh_data()
        self.animate_progress_bar()
        self.set_toast(f"Deleted ritual: '{curr_task.title}'")

    def action_cycle_theme(self) -> None:
        themes = ["lifeos", "phosphor", "amber"]
        next_idx = (themes.index(self.theme_name) + 1) % len(themes) if self.theme_name in themes else 0
        self.theme_name = themes[next_idx]
        self.theme_obj = get_theme(self.theme_name, self.caps)
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
        self._refresh_all_widgets()
        self.set_toast(f"Theme switched to: {self.theme_obj.label}")


# ===========================================================================
# CLI Entrypoint
# ===========================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="lifeOS Daily — Ritual & Momentum Terminal App")
    parser.add_argument("--theme", choices=["lifeos", "phosphor", "amber"], default=None, help="Startup visual theme")
    parser.add_argument("--db", type=Path, default=None, help="Custom SQLite database file")
    args = parser.parse_args()

    app = DailyOS(db_path=args.db, theme_name=args.theme)
    app.run()


if __name__ == "__main__":
    main()
