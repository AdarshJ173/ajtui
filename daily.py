#!/usr/bin/env python3
"""
◆ lifeOS Daily
A keyboard-first, state-of-the-art terminal daily routine OS with calendar navigation.
"""

from __future__ import annotations

import calendar
import datetime
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, List, Optional, Tuple

from rich.segment import Segment
from rich.style import Style
from rich.text import Text

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Button, Footer, Header, Input, Label, Static

# ---------------------------------------------------------------------------
# Database & Persistence Layer
# ---------------------------------------------------------------------------

DB_DIR = Path.home() / ".lifeos"
DB_PATH = DB_DIR / "daily.db"


@dataclass
class RoutineTask:
    id: int
    title: str
    position: int
    active: int
    created_at: str


@dataclass
class CompletionStatus:
    task_id: int
    done: bool
    completed_at: Optional[str]


class DatabaseManager:
    """Robust SQLite persistence layer for lifeOS Daily."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._ensure_initialized()

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_initialized(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS routine_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS completions (
                    task_id INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0,
                    completed_at TEXT,
                    PRIMARY KEY (task_id, date),
                    FOREIGN KEY (task_id) REFERENCES routine_tasks(id) ON DELETE CASCADE
                )
                """
            )
            # Create indexing for rapid date/streak lookups
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_completions_date ON completions(date)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_routine_position ON routine_tasks(position)"
            )

            # Auto-seed initial tasks if the table is freshly created and empty
            cur = conn.execute("SELECT COUNT(*) as count FROM routine_tasks")
            if cur.fetchone()["count"] == 0:
                seed_tasks = [
                    "Morning sunlight & hydration",
                    "Deep Work — 90 min focused sprint",
                    "Gym / Zone 2 cardio session",
                    "Read 20 pages (non-fiction)",
                    "Evening retrospective & journal",
                ]
                now = datetime.datetime.now().isoformat()
                for i, title in enumerate(seed_tasks):
                    conn.execute(
                        "INSERT INTO routine_tasks (title, position, active, created_at) VALUES (?, ?, 1, ?)",
                        (title, i, now),
                    )

    def get_tasks(self) -> List[RoutineTask]:
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT id, title, position, active, created_at FROM routine_tasks WHERE active = 1 ORDER BY position ASC, id ASC"
            )
            return [
                RoutineTask(
                    id=row["id"],
                    title=row["title"],
                    position=row["position"],
                    active=row["active"],
                    created_at=row["created_at"],
                )
                for row in cur.fetchall()
            ]

    def add_task(self, title: str) -> RoutineTask:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("Task title cannot be empty")
        now = datetime.datetime.now().isoformat()
        with self._conn() as conn:
            cur = conn.execute("SELECT MAX(position) as max_pos FROM routine_tasks")
            row = cur.fetchone()
            next_pos = (row["max_pos"] + 1) if (row and row["max_pos"] is not None) else 0
            cur = conn.execute(
                "INSERT INTO routine_tasks (title, position, active, created_at) VALUES (?, ?, 1, ?)",
                (clean_title, next_pos, now),
            )
            task_id = cur.lastrowid
            return RoutineTask(
                id=task_id,
                title=clean_title,
                position=next_pos,
                active=1,
                created_at=now,
            )

    def update_task_title(self, task_id: int, new_title: str) -> None:
        clean_title = new_title.strip()
        if not clean_title:
            raise ValueError("Task title cannot be empty")
        with self._conn() as conn:
            conn.execute(
                "UPDATE routine_tasks SET title = ? WHERE id = ?",
                (clean_title, task_id),
            )

    def delete_task(self, task_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM routine_tasks WHERE id = ?", (task_id,))

    def reorder_task(self, task_id: int, direction: int) -> None:
        """direction: -1 for UP, +1 for DOWN"""
        tasks = self.get_tasks()
        idx = next((i for i, t in enumerate(tasks) if t.id == task_id), -1)
        if idx == -1:
            return
        target_idx = idx + direction
        if target_idx < 0 or target_idx >= len(tasks):
            return

        # Swap in list and update positions in DB
        tasks[idx], tasks[target_idx] = tasks[target_idx], tasks[idx]
        with self._conn() as conn:
            for i, t in enumerate(tasks):
                conn.execute(
                    "UPDATE routine_tasks SET position = ? WHERE id = ?",
                    (i, t.id),
                )

    def get_day_completions(self, date_str: str) -> dict[int, CompletionStatus]:
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT task_id, done, completed_at FROM completions WHERE date = ?",
                (date_str,),
            )
            res = {}
            for row in cur.fetchall():
                res[row["task_id"]] = CompletionStatus(
                    task_id=row["task_id"],
                    done=bool(row["done"]),
                    completed_at=row["completed_at"],
                )
            return res

    def toggle_completion(self, task_id: int, date_str: str) -> bool:
        """Toggles the completion state for a given task and date. Returns new state."""
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT done FROM completions WHERE task_id = ? AND date = ?",
                (task_id, date_str),
            )
            row = cur.fetchone()
            new_done = 1
            if row is not None:
                new_done = 0 if row["done"] == 1 else 1

            completed_at = datetime.datetime.now().isoformat() if new_done else None
            conn.execute(
                """
                INSERT INTO completions (task_id, date, done, completed_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(task_id, date) DO UPDATE SET
                    done = excluded.done,
                    completed_at = excluded.completed_at
                """,
                (task_id, date_str, new_done, completed_at),
            )
            return bool(new_done)

    def get_month_completion_stats(
        self, year: int, month: int
    ) -> dict[str, Tuple[int, int]]:
        """Returns map of YYYY-MM-DD -> (done_count, total_tasks_count)"""
        tasks = self.get_tasks()
        total_tasks = len(tasks)
        if total_tasks == 0:
            return {}

        start_date = f"{year:04d}-{month:02d}-01"
        last_day = calendar.monthrange(year, month)[1]
        end_date = f"{year:04d}-{month:02d}-{last_day:02d}"

        with self._conn() as conn:
            cur = conn.execute(
                """
                SELECT date, SUM(done) as done_cnt
                FROM completions
                WHERE date >= ? AND date <= ? AND task_id IN (SELECT id FROM routine_tasks WHERE active = 1)
                GROUP BY date
                """,
                (start_date, end_date),
            )
            res = {}
            for row in cur.fetchall():
                res[row["date"]] = (int(row["done_cnt"] or 0), total_tasks)
            return res

    def calculate_streak(self, today_date: datetime.date) -> int:
        """
        Calculates consecutive streak of 100% completed days ending today or yesterday.
        """
        tasks = self.get_tasks()
        total_tasks = len(tasks)
        if total_tasks == 0:
            return 0

        streak = 0
        current_check = today_date

        with self._conn() as conn:
            # Check today first
            cur = conn.execute(
                """
                SELECT COUNT(*) as done_cnt FROM completions
                WHERE date = ? AND done = 1 AND task_id IN (SELECT id FROM routine_tasks WHERE active = 1)
                """,
                (current_check.strftime("%Y-%m-%d"),),
            )
            today_done = cur.fetchone()["done_cnt"]
            if today_done == total_tasks:
                streak += 1
                current_check -= datetime.timedelta(days=1)
            else:
                # If today isn't finished yet, streak can still be alive from yesterday!
                current_check -= datetime.timedelta(days=1)

            # Check consecutive backward days
            while True:
                d_str = current_check.strftime("%Y-%m-%d")
                cur = conn.execute(
                    """
                    SELECT COUNT(*) as done_cnt FROM completions
                    WHERE date = ? AND done = 1 AND task_id IN (SELECT id FROM routine_tasks WHERE active = 1)
                    """,
                    (d_str,),
                )
                day_done = cur.fetchone()["done_cnt"]
                if day_done == total_tasks:
                    streak += 1
                    current_check -= datetime.timedelta(days=1)
                else:
                    break

        return streak


# ---------------------------------------------------------------------------
# UI Widgets & Custom Renderables
# ---------------------------------------------------------------------------


class TopBar(Widget):
    """Refined futuristic lifeOS header with live date display and streak."""

    viewed_date = reactive(datetime.date.today)
    streak_count = reactive(0)

    def render(self) -> Text:
        today = datetime.date.today()
        is_today = self.viewed_date == today

        # Left logo
        text = Text()
        text.append(" ◆ ", style="bold #00E5FF")
        text.append("lifeOS", style="bold #FFFFFF")
        text.append(" daily", style="#64748B")

        # Center formatted date
        date_fmt = self.viewed_date.strftime("%a, %b %d")
        if self.viewed_date.year != today.year:
            date_fmt = self.viewed_date.strftime("%a, %b %d, %Y")

        date_segment = Text()
        date_segment.append(f"  {date_fmt}  ", style="bold #E2E8F0")
        if is_today:
            date_segment.append("— TODAY", style="bold #00F59B")
        elif self.viewed_date > today:
            date_segment.append("— FUTURE", style="#F59E0B")
        else:
            days_ago = (today - self.viewed_date).days
            date_segment.append(f"— {days_ago}d ago", style="#64748B")

        # Right streak
        streak_seg = Text()
        if self.streak_count > 0:
            streak_seg.append(f"🔥 {self.streak_count} day streak", style="bold #FF7B00")
        else:
            streak_seg.append("⚡ 0 day streak", style="#64748B")
        streak_seg.append(" ")

        # Total layout assembly
        total_width = max(self.size.width, 60)
        left_len = text.cell_len
        date_len = date_segment.cell_len
        right_len = streak_seg.cell_len

        spacing_left = max(2, (total_width - left_len - date_len - right_len) // 2)
        spacing_right = max(2, total_width - left_len - right_len - date_len - spacing_left)

        res = Text()
        res.append_text(text)
        res.append(" " * spacing_left)
        res.append_text(date_segment)
        res.append(" " * spacing_right)
        res.append_text(streak_seg)
        return res


class DailyProgressBar(Widget):
    """Custom aesthetic segmented progress bar with contextual color grade."""

    done_count = reactive(0)
    total_count = reactive(0)
    celebrate_anim = reactive(False)

    def render(self) -> Text:
        t = Text()
        if self.total_count == 0:
            t.append("  0/0 · 0%   No tasks defined", style="#475569")
            return t

        pct = int(round((self.done_count / self.total_count) * 100)) if self.total_count else 0
        pct = max(0, min(100, pct))

        bar_width = max(10, min(36, self.size.width - 28))
        filled_chars = int(round((pct / 100.0) * bar_width))
        empty_chars = bar_width - filled_chars

        if pct == 100:
            fill_style = "bold #00F59B"
            num_style = "bold #00F59B"
        elif pct >= 50:
            fill_style = "bold #00E5FF"
            num_style = "bold #00E5FF"
        elif pct > 0:
            fill_style = "bold #F59E0B"
            num_style = "bold #F59E0B"
        else:
            fill_style = "#334155"
            num_style = "#64748B"

        t.append("  [", style="#334155")
        t.append("█" * filled_chars, style=fill_style)
        t.append("░" * empty_chars, style="#1E293B")
        t.append("] ", style="#334155")

        t.append(f"{self.done_count}/{self.total_count}", style=num_style)
        t.append(" · ", style="#475569")
        t.append(f"{pct}%", style=num_style)

        if pct == 100:
            t.append("  ✨ Daily Routine Completed! Stellar work.", style="bold #00F59B")
        elif pct == 0:
            t.append("  Focus in. Win the morning.", style="#64748B")

        return t


class TaskItemRow(Widget):
    """Interactive task row rendered with precision typography and micro-states."""

    def __init__(
        self,
        task: RoutineTask,
        done: bool,
        is_selected: bool = False,
        duplicate_num: int = 0,
        flash_tick: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.task = task
        self.done = done
        self.is_selected = is_selected
        self.duplicate_num = duplicate_num
        self.flash_tick = flash_tick

    def render(self) -> Text:
        text = Text()
        # Left margin padding
        text.append("  ")

        # Checkbox styling
        if self.done:
            if self.flash_tick:
                text.append("● [✓] ", style="bold #FFFFFF on #00F59B")
            else:
                text.append("✓ ", style="bold #00F59B")
        else:
            text.append("○ ", style="#475569")

        # Title formatting & duplicate numbering
        title_display = self.task.title
        if self.duplicate_num > 1:
            title_display = f"{title_display} (#{self.duplicate_num})"

        if self.done:
            text.append(title_display, style="strike #64748B")
        else:
            if self.is_selected:
                text.append(title_display, style="bold #FFFFFF")
            else:
                text.append(title_display, style="#CBD5E1")

        return text


class MonthCalendarWidget(Widget):
    """
    Compact keyboard navigable month calendar view with completion markers:
    ● = 100% complete
    ◐ = partial complete
    · = 0% complete
    (nothing for future dates)
    """

    cursor_date = reactive(datetime.date.today)
    selected_date = reactive(datetime.date.today)

    def __init__(self, db: DatabaseManager, **kwargs):
        super().__init__(**kwargs)
        self.db = db
        self.stats: dict[str, Tuple[int, int]] = {}
        self.refresh_stats()

    def refresh_stats(self) -> None:
        self.stats = self.db.get_month_completion_stats(
            self.cursor_date.year, self.cursor_date.month
        )
        self.refresh()

    def watch_cursor_date(self, old_date: datetime.date, new_date: datetime.date) -> None:
        if old_date.year != new_date.year or old_date.month != new_date.month:
            self.refresh_stats()
        else:
            self.refresh()

    def render(self) -> Text:
        t = Text()
        today = datetime.date.today()
        year = self.cursor_date.year
        month = self.cursor_date.month

        # Month Header
        month_name = datetime.date(year, month, 1).strftime("%B %Y")
        t.append(f"\n   ◀  {month_name.center(16)}  ▶\n\n", style="bold #00E5FF")

        # Day headers
        t.append("   MO  TU  WE  TH  FR  SA  SU\n", style="bold #64748B")

        cal = calendar.Calendar(firstweekday=0)
        month_days = cal.monthdatescalendar(year, month)

        for week in month_days:
            line = Text("   ")
            for day in week:
                is_current_month = day.month == month
                is_cursor = day == self.cursor_date
                is_selected = day == self.selected_date
                is_today = day == today
                is_future = day > today

                day_str = day.strftime("%Y-%m-%d")
                stat = self.stats.get(day_str)

                # Determine completion marker
                marker = " "
                marker_style = "#334155"
                if is_current_month and not is_future and stat:
                    done_cnt, total_cnt = stat
                    if total_cnt > 0:
                        if done_cnt == total_cnt:
                            marker = "●"
                            marker_style = "#00F59B"
                        elif done_cnt > 0:
                            marker = "◐"
                            marker_style = "#00E5FF"
                        else:
                            marker = "·"
                            marker_style = "#475569"
                elif is_current_month and not is_future:
                    marker = "·"
                    marker_style = "#334155"

                day_num = f"{day.day:2d}"

                if not is_current_month:
                    line.append(f"{day_num} ", style="#1E293B")
                elif is_cursor:
                    line.append(f"{day_num}", style="bold #0A0E14 on #00E5FF")
                    line.append(f"{marker}", style=marker_style)
                elif is_selected:
                    line.append(f"{day_num}", style="bold #0A0E14 on #00F59B")
                    line.append(f"{marker}", style=marker_style)
                elif is_today:
                    line.append(f"{day_num}", style="bold underline #00F59B")
                    line.append(f"{marker}", style=marker_style)
                else:
                    line.append(f"{day_num}", style="#94A3B8")
                    line.append(f"{marker}", style=marker_style)

                line.append(" ")
            t.append_text(line)
            t.append("\n")

        # Legend
        t.append("\n  ● 100%   ◐ Partial   · None\n", style="#475569")
        t.append("  [Arrows] Move  [Enter] Select\n", style="#334155")
        return t


# ---------------------------------------------------------------------------
# Modal Dialogs with Clean Keyboard Traps & Error Validation
# ---------------------------------------------------------------------------


class TaskInputDialog(ModalScreen[Optional[str]]):
    """Keyboard-first clean modal for Adding and Inline Renaming tasks."""

    DEFAULT_CSS = """
    TaskInputDialog {
        align: center middle;
        background: rgba(10, 14, 20, 0.85);
    }
    #dialog_box {
        width: 54;
        height: auto;
        border: round #00E5FF;
        background: #0D121B;
        padding: 1 2;
    }
    #dialog_title {
        text-style: bold;
        color: #00E5FF;
        margin-bottom: 1;
    }
    #dialog_error {
        color: #EF4444;
        margin-top: 1;
        min-height: 1;
    }
    #dialog_input {
        border: tall #334155;
        background: #0A0E14;
        color: #FFFFFF;
    }
    #dialog_input:focus {
        border: tall #00E5FF;
    }
    #hints {
        color: #64748B;
        margin-top: 1;
        text-align: right;
    }
    """

    def __init__(
        self,
        title: str,
        initial_value: str = "",
        placeholder: str = "Enter routine task title...",
    ):
        super().__init__()
        self.dialog_title_text = title
        self.initial_value = initial_value
        self.placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog_box"):
            yield Label(self.dialog_title_text, id="dialog_title")
            yield Input(
                value=self.initial_value,
                placeholder=self.placeholder,
                id="dialog_input",
            )
            yield Label("", id="dialog_error")
            yield Label("Enter to Confirm  ·  Esc to Cancel", id="hints")

    def on_mount(self) -> None:
        inp = self.query_one(Input)
        inp.focus()
        inp.cursor_position = len(self.initial_value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        val = event.value.strip()
        if not val:
            self.query_one("#dialog_error", Label).update("Task title cannot be empty")
            return
        self.dismiss(val)

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)


class ConfirmDeleteDialog(ModalScreen[bool]):
    """Clean modal asking to confirm cascading task deletion."""

    DEFAULT_CSS = """
    ConfirmDeleteDialog {
        align: center middle;
        background: rgba(10, 14, 20, 0.85);
    }
    #confirm_box {
        width: 52;
        height: auto;
        border: round #EF4444;
        background: #0D121B;
        padding: 1 2;
    }
    #confirm_title {
        text-style: bold;
        color: #EF4444;
        margin-bottom: 1;
    }
    #confirm_msg {
        color: #CBD5E1;
        margin-bottom: 1;
    }
    #confirm_buttons {
        height: 3;
        align: right middle;
    }
    Button {
        margin-left: 1;
    }
    """

    def __init__(self, task_title: str):
        super().__init__()
        self.task_title = task_title

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm_box"):
            yield Label("Delete Routine Task", id="confirm_title")
            yield Label(
                f"Are you sure you want to delete:\n'{self.task_title}'?\n\nThis will remove all completion history.",
                id="confirm_msg",
            )
            with Horizontal(id="confirm_buttons"):
                yield Button("Cancel (Esc)", id="btn_cancel", variant="default")
                yield Button("Delete (Enter)", id="btn_delete", variant="error")

    def on_mount(self) -> None:
        self.query_one("#btn_delete", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_delete":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def on_key(self, event: events.Key) -> None:
        if event.key in ("escape", "n"):
            event.stop()
            self.dismiss(False)
        elif event.key in ("enter", "y"):
            event.stop()
            self.dismiss(True)


# ---------------------------------------------------------------------------
# Main Routine Checklist Component
# ---------------------------------------------------------------------------


class RoutineListWidget(Widget):
    """
    The heart of lifeOS daily: shows the routine tasks for the currently viewed date.
    Keyboard navigation, instant reordering, animated check-off.
    """

    selected_index = reactive(0)
    flash_index: Optional[int] = None

    def __init__(
        self,
        db: DatabaseManager,
        viewed_date: datetime.date,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.db = db
        self.viewed_date = viewed_date
        self.tasks: List[RoutineTask] = []
        self.completions: dict[int, CompletionStatus] = {}
        self.reload_data()

    def reload_data(self) -> None:
        self.tasks = self.db.get_tasks()
        date_str = self.viewed_date.strftime("%Y-%m-%d")
        self.completions = self.db.get_day_completions(date_str)
        if self.selected_index >= len(self.tasks):
            self.selected_index = max(0, len(self.tasks) - 1)
        self.refresh()

    def get_counts(self) -> Tuple[int, int]:
        total = len(self.tasks)
        done = sum(
            1
            for t in self.tasks
            if self.completions.get(t.id) and self.completions[t.id].done
        )
        return done, total

    def move_cursor(self, delta: int) -> None:
        if not self.tasks:
            return
        new_idx = max(0, min(len(self.tasks) - 1, self.selected_index + delta))
        if new_idx != self.selected_index:
            self.selected_index = new_idx
            self.refresh()

    def render(self) -> Text:
        t = Text()
        if not self.tasks:
            t.append("\n\n   ◆  No daily routine tasks yet.\n", style="bold #00E5FF")
            t.append("      Press ", style="#64748B")
            t.append("a", style="bold #00F59B")
            t.append(" to add your first recurring task.\n\n", style="#64748B")
            t.append(
                "      Daily tasks repeat every single day automatically.",
                style="#334155",
            )
            return t

        # Calculate duplicate titles for clean numbering
        title_counts: dict[str, int] = {}
        title_occurrences: dict[int, int] = {}
        for task in self.tasks:
            title_counts[task.title] = title_counts.get(task.title, 0) + 1

        seen_counts: dict[str, int] = {}
        for task in self.tasks:
            if title_counts[task.title] > 1:
                seen_counts[task.title] = seen_counts.get(task.title, 0) + 1
                title_occurrences[task.id] = seen_counts[task.title]
            else:
                title_occurrences[task.id] = 0

        total_width = max(self.size.width, 40)
        t.append("\n")

        for idx, task in enumerate(self.tasks):
            is_selected = idx == self.selected_index
            comp = self.completions.get(task.id)
            is_done = comp.done if comp else False
            dup_num = title_occurrences.get(task.id, 0)
            is_flash = idx == self.flash_index

            row_text = Text()

            # Selection bar
            if is_selected:
                row_text.append(" ▎", style="bold #00E5FF")
            else:
                row_text.append("  ", style="#0A0E14")

            # Check indicator
            if is_done:
                if is_flash:
                    row_text.append(" [✓] ", style="bold #0A0E14 on #00F59B")
                else:
                    row_text.append("  ✓  ", style="bold #00F59B")
            else:
                row_text.append("  ○  ", style="#475569")

            # Title
            title_str = task.title
            if dup_num > 1:
                title_str = f"{title_str} ({dup_num})"

            max_title_len = max(10, total_width - 20)
            if len(title_str) > max_title_len:
                title_str = title_str[: max_title_len - 1] + "…"

            if is_done:
                row_text.append(title_str, style="strike #475569")
            else:
                if is_selected:
                    row_text.append(title_str, style="bold #FFFFFF")
                else:
                    row_text.append(title_str, style="#CBD5E1")

            # Completed timestamp indicator if available
            if is_done and comp and comp.completed_at:
                try:
                    dt = datetime.datetime.fromisoformat(comp.completed_at)
                    time_str = dt.strftime("%H:%M")
                    pad_len = max(
                        2, total_width - row_text.cell_len - len(time_str) - 4
                    )
                    row_text.append(" " * pad_len)
                    row_text.append(time_str, style="#334155")
                except Exception:
                    pass

            # Wrap in soft background band for selected row
            if is_selected:
                row_styled = Text()
                # Pad row to panel width for glowing band feel
                row_len = row_text.cell_len
                pad_tail = max(0, total_width - row_len - 2)
                row_text.append(" " * pad_tail)
                row_text.stylize(Style(bgcolor="#131B26"), 0, len(row_text))
                t.append_text(row_text)
            else:
                t.append_text(row_text)

            t.append("\n\n")

        return t


# ---------------------------------------------------------------------------
# Main Application Screen
# ---------------------------------------------------------------------------


class DailyOS(App):
    """lifeOS Daily — Master Keyboard-First Daily Routine Terminal App."""

    CSS = """
    Screen {
        background: #0A0E14;
        color: #E2E8F0;
        layout: vertical;
    }

    #header_container {
        height: 3;
        background: #0D121B;
        border-bottom: solid #1E293B;
        padding: 0 1;
    }

    #main_body {
        height: 1fr;
        layout: horizontal;
    }

    #checklist_container {
        width: 1fr;
        height: 1fr;
        border-right: solid #1E293B;
        padding: 0 1;
        layout: vertical;
    }

    #routine_list {
        height: 1fr;
    }

    #progress_dock {
        height: 3;
        border-top: solid #1E293B;
        background: #0D121B;
        padding: 0 1;
    }

    #calendar_container {
        width: 38;
        height: 1fr;
        background: #0A0E14;
        padding: 0 1;
    }

    #calendar_container.hidden {
        display: none;
    }

    #flash_notification {
        height: 1;
        background: #00E5FF;
        color: #0A0E14;
        text-style: bold;
        text-align: center;
        display: none;
    }

    #min_size_notice {
        display: none;
        background: #0A0E14;
        color: #F59E0B;
        text-align: center;
        padding: 2;
        text-style: bold;
    }

    Footer {
        background: #0D121B;
        color: #64748B;
        border-top: solid #1E293B;
    }
    """

    BINDINGS = [
        Binding("space", "toggle_task", "Toggle", show=True),
        Binding("enter", "toggle_task", "Toggle", show=False),
        Binding("a", "add_task", "Add", show=True),
        Binding("e", "edit_task", "Rename", show=True),
        Binding("d", "delete_task", "Delete", show=True),
        Binding("k", "move_up", "Up", show=False),
        Binding("j", "move_down", "Down", show=False),
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("K", "reorder_up", "Shift Up", show=False),
        Binding("J", "reorder_down", "Shift Down", show=False),
        Binding("ctrl+up", "reorder_up", "Reorder ↑", show=False),
        Binding("ctrl+down", "reorder_down", "Reorder ↓", show=False),
        Binding("left", "prev_day", "◀ Day", show=True),
        Binding("h", "prev_day", "◀ Day", show=False),
        Binding("right", "next_day", "Day ▶", show=True),
        Binding("l", "next_day", "Day ▶", show=False),
        Binding("t", "jump_today", "Today", show=True),
        Binding("c", "toggle_calendar", "Calendar", show=True),
        Binding("q", "quit_app", "Quit", show=True),
        Binding("escape", "escape_action", "Back/Esc", show=False),
    ]

    viewed_date = reactive(datetime.date.today())
    calendar_mode = reactive(False)
    calendar_active_focus = reactive(False)

    def __init__(self, db_path: Path = DB_PATH):
        super().__init__()
        self.db = DatabaseManager(db_path)
        self.last_checked_date = datetime.date.today()

    def compose(self) -> ComposeResult:
        with Container(id="header_container"):
            yield TopBar(id="top_bar")

        yield Label("", id="flash_notification")

        with Horizontal(id="main_body"):
            with Vertical(id="checklist_container"):
                yield RoutineListWidget(
                    db=self.db,
                    viewed_date=self.viewed_date,
                    id="routine_list",
                )
                yield DailyProgressBar(id="progress_dock")

            with Vertical(id="calendar_container"):
                yield MonthCalendarWidget(db=self.db, id="month_calendar")

        with Container(id="min_size_notice"):
            yield Static(
                "Terminal too small.\nPlease resize to at least 50×15 for lifeOS Daily.",
            )

        yield Footer()

    def on_mount(self) -> None:
        self.title = "lifeOS Daily"
        self._update_all_views()
        # Set tick interval to check for day rollovers at midnight
        self.set_interval(1.0, self._check_midnight_rollover)

    def on_resize(self, event: events.Resize) -> None:
        min_notice = self.query_one("#min_size_notice")
        main_body = self.query_one("#main_body")
        hdr = self.query_one("#header_container")
        if event.size.width < 50 or event.size.height < 15:
            min_notice.styles.display = "block"
            main_body.styles.display = "none"
            hdr.styles.display = "none"
        else:
            min_notice.styles.display = "none"
            main_body.styles.display = "block"
            hdr.styles.display = "block"

    def _check_midnight_rollover(self) -> None:
        now_today = datetime.date.today()
        if now_today != self.last_checked_date:
            was_viewing_today = self.viewed_date == self.last_checked_date
            self.last_checked_date = now_today
            if was_viewing_today:
                self.viewed_date = now_today
                self.flash_message("Midnight reached — Rolled over to new day")
            self._update_all_views()

    def flash_message(self, message: str, is_error: bool = False) -> None:
        lbl = self.query_one("#flash_notification", Label)
        lbl.update(f" {message} ")
        if is_error:
            lbl.styles.background = "#EF4444"
            lbl.styles.color = "#FFFFFF"
        else:
            lbl.styles.background = "#00E5FF"
            lbl.styles.color = "#0A0E14"
        lbl.styles.display = "block"
        self.set_timer(2.2, self._clear_flash)

    def _clear_flash(self) -> None:
        lbl = self.query_one("#flash_notification", Label)
        lbl.styles.display = "none"

    def _update_all_views(self) -> None:
        # Update header
        top_bar = self.query_one(TopBar)
        top_bar.viewed_date = self.viewed_date
        top_bar.streak_count = self.db.calculate_streak(datetime.date.today())

        # Update Routine Checklist
        routine_list = self.query_one(RoutineListWidget)
        routine_list.viewed_date = self.viewed_date
        routine_list.reload_data()

        # Update Progress Bar
        done_cnt, tot_cnt = routine_list.get_counts()
        prog = self.query_one(DailyProgressBar)
        prog.done_count = done_cnt
        prog.total_count = tot_cnt

        # Update Calendar
        cal = self.query_one(MonthCalendarWidget)
        cal.selected_date = self.viewed_date
        if not self.calendar_active_focus:
            cal.cursor_date = self.viewed_date
        cal.refresh_stats()

    # -----------------------------------------------------------------------
    # Action Handlers
    # -----------------------------------------------------------------------

    def action_toggle_task(self) -> None:
        if self.calendar_active_focus:
            # Enter in calendar mode selects the hovered date!
            cal = self.query_one(MonthCalendarWidget)
            self.viewed_date = cal.cursor_date
            self.calendar_active_focus = False
            self._update_all_views()
            self.flash_message(f"Jumped to {self.viewed_date.strftime('%a, %b %d')}")
            return

        today = datetime.date.today()
        if self.viewed_date > today:
            self.flash_message("Cannot complete tasks in the future — Not yet!", is_error=True)
            return

        routine_list = self.query_one(RoutineListWidget)
        if not routine_list.tasks:
            self.flash_message("No tasks to toggle. Press 'a' to add one.", is_error=True)
            return

        curr_task = routine_list.tasks[routine_list.selected_index]
        date_str = self.viewed_date.strftime("%Y-%m-%d")

        # Perform atomic toggle
        new_state = self.db.toggle_completion(curr_task.id, date_str)

        # Micro-delight animation flash
        routine_list.flash_index = routine_list.selected_index
        self.set_timer(0.2, self._clear_tick_flash)

        self._update_all_views()

    def _clear_tick_flash(self) -> None:
        routine_list = self.query_one(RoutineListWidget)
        routine_list.flash_index = None
        routine_list.refresh()

    def action_move_up(self) -> None:
        if self.calendar_active_focus:
            cal = self.query_one(MonthCalendarWidget)
            cal.cursor_date -= datetime.timedelta(days=7)
        else:
            self.query_one(RoutineListWidget).move_cursor(-1)

    def action_move_down(self) -> None:
        if self.calendar_active_focus:
            cal = self.query_one(MonthCalendarWidget)
            cal.cursor_date += datetime.timedelta(days=7)
        else:
            self.query_one(RoutineListWidget).move_cursor(1)

    def action_prev_day(self) -> None:
        if self.calendar_active_focus:
            cal = self.query_one(MonthCalendarWidget)
            cal.cursor_date -= datetime.timedelta(days=1)
        else:
            self.viewed_date -= datetime.timedelta(days=1)
            self._update_all_views()

    def action_next_day(self) -> None:
        if self.calendar_active_focus:
            cal = self.query_one(MonthCalendarWidget)
            cal.cursor_date += datetime.timedelta(days=1)
        else:
            self.viewed_date += datetime.timedelta(days=1)
            self._update_all_views()

    def action_jump_today(self) -> None:
        self.viewed_date = datetime.date.today()
        cal = self.query_one(MonthCalendarWidget)
        cal.cursor_date = self.viewed_date
        self.calendar_active_focus = False
        self._update_all_views()
        self.flash_message("Today")

    def action_toggle_calendar(self) -> None:
        cal_container = self.query_one("#calendar_container")
        cal = self.query_one(MonthCalendarWidget)
        if cal_container.has_class("hidden"):
            cal_container.remove_class("hidden")
            self.calendar_active_focus = True
            cal.cursor_date = self.viewed_date
            self.flash_message("Calendar focus active (Arrows to browse, Enter to pick)")
        else:
            if not self.calendar_active_focus:
                self.calendar_active_focus = True
                self.flash_message("Calendar focus active")
            else:
                self.calendar_active_focus = False
                self.flash_message("Checklist focus active")

    def action_reorder_up(self) -> None:
        routine_list = self.query_one(RoutineListWidget)
        if not routine_list.tasks or routine_list.selected_index <= 0:
            return
        curr_task = routine_list.tasks[routine_list.selected_index]
        self.db.reorder_task(curr_task.id, -1)
        self._update_all_views()
        routine_list.selected_index = self._clamp_index(routine_list.selected_index - 1)

    def action_reorder_down(self) -> None:
        routine_list = self.query_one(RoutineListWidget)
        if not routine_list.tasks or routine_list.selected_index >= len(routine_list.tasks) - 1:
            return
        curr_task = routine_list.tasks[routine_list.selected_index]
        self.db.reorder_task(curr_task.id, +1)
        self._update_all_views()
        routine_list.selected_index = self._clamp_index(routine_list.selected_index + 1)

    def _clamp_index(self, idx: int) -> int:
        """Keep cursor within valid bounds after list mutation."""
        n = len(self.query_one(RoutineListWidget).tasks)
        return max(0, min(n - 1, idx))

    def action_add_task(self) -> None:
        def on_task_added(title: Optional[str]) -> None:
            if title:
                try:
                    new_task = self.db.add_task(title)
                    routine_list = self.query_one(RoutineListWidget)
                    self._update_all_views()
                    # Select newly added task at end
                    routine_list.selected_index = len(routine_list.tasks) - 1
                    self.flash_message(f"Added routine task: '{title}'")
                except Exception as ex:
                    self.flash_message(f"Error: {ex}", is_error=True)

        self.push_screen(
            TaskInputDialog(title="Add Daily Routine Task"), on_task_added
        )

    def action_edit_task(self) -> None:
        routine_list = self.query_one(RoutineListWidget)
        if not routine_list.tasks:
            self.flash_message("No tasks to rename", is_error=True)
            return

        curr_task = routine_list.tasks[routine_list.selected_index]

        def on_task_edited(new_title: Optional[str]) -> None:
            if new_title and new_title != curr_task.title:
                try:
                    self.db.update_task_title(curr_task.id, new_title)
                    self._update_all_views()
                    self.flash_message(f"Renamed to: '{new_title}'")
                except Exception as ex:
                    self.flash_message(f"Error: {ex}", is_error=True)

        self.push_screen(
            TaskInputDialog(
                title="Rename Daily Task",
                initial_value=curr_task.title,
            ),
            on_task_edited,
        )

    def action_delete_task(self) -> None:
        routine_list = self.query_one(RoutineListWidget)
        if not routine_list.tasks:
            self.flash_message("No tasks to delete", is_error=True)
            return

        curr_task = routine_list.tasks[routine_list.selected_index]

        def on_delete_confirmed(confirmed: Optional[bool]) -> None:
            if confirmed:
                try:
                    self.db.delete_task(curr_task.id)
                    self._update_all_views()
                    self.flash_message(f"Deleted task '{curr_task.title}'")
                except Exception as ex:
                    self.flash_message(f"Error: {ex}", is_error=True)

        self.push_screen(ConfirmDeleteDialog(curr_task.title), on_delete_confirmed)

    def action_escape_action(self) -> None:
        if self.calendar_active_focus:
            self.calendar_active_focus = False
            self.flash_message("Checklist focus active")

    def action_quit_app(self) -> None:
        self.exit(0)


# ---------------------------------------------------------------------------
# Production Entry Point
# ---------------------------------------------------------------------------


def main() -> None:
    app = DailyOS()
    app.run()


if __name__ == "__main__":
    main()
