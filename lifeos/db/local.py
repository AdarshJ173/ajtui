"""
lifeOS Local Persistence Layer
==============================
SQLite storage with schema migrations, outbox queue for cloud sync,
dual-mirrored plain text journal files (~/.lifeos/journal/YYYY-MM-DD.txt),
and the full Execution OS v3 data layer (Projects, Actions, Priorities, TimeBlocks, Inbox).
"""

from __future__ import annotations

import calendar
import datetime
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from lifeos.core.models import (
    Action,
    ActionDependency,
    ActionStatus,
    BlockKind,
    BlockStatus,
    Completion,
    DailyPriority,
    EnergyLevel,
    InboxItem,
    InboxStatus,
    JournalEntry,
    Project,
    ProjectStatus,
    Task,
    TimeBlock,
    current_iso_time,
    generate_uuid,
    is_valid_physical_action,
)

DEFAULT_ROUTINES = [
    "Morning sunlight + Hydration (500ml)",
    "Deep focus session (90 mins)",
    "Zone 2 Cardio or Strength workout",
    "Read 15 pages of non-fiction",
    "Nightly retrospective & tomorrow plan",
]

DEFAULT_PROJECTS = [
    {
        "title": "lifeOS Planner MVP",
        "area": "Career",
        "outcome": "Plan today in <5 minutes and finish a focused block.",
        "actions": [
            ("Define SQLite schema for projects/actions/blocks", 35, ActionStatus.NEXT),
            ("Build Today Command Center", 90, ActionStatus.NEXT),
            ("Add action-to-block scheduling", 75, ActionStatus.NEXT),
            ("Decide calendar-provider integration", 30, ActionStatus.WAITING),
        ],
    },
    {
        "title": "ML Foundations",
        "area": "Learning",
        "outcome": "Finish Week 1 coursework and exercises.",
        "actions": [
            ("Complete lesson 3 video and notes", 60, ActionStatus.NEXT),
            ("Implement matrix decomposition exercise", 45, ActionStatus.NEXT),
        ],
    },
    {
        "title": "Physical Health & Conditioning",
        "area": "Health",
        "outcome": "Consistent daily physical conditioning and vitality.",
        "actions": [
            ("Cardio / strength training session", 45, ActionStatus.NEXT),
        ],
    },
]


class DatabaseManager:
    """Robust SQLite storage and local journal file manager."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        journal_dir: Optional[Path] = None,
    ):
        if db_path is None:
            config_dir = Path.home() / ".lifeos"
            config_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = config_dir / "daily.db"
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        if journal_dir is None:
            self.journal_dir = self.db_path.parent / "journal"
        else:
            self.journal_dir = Path(journal_dir)
        self.journal_dir.mkdir(parents=True, exist_ok=True)

        self.conflicts_dir = self.journal_dir / "conflicts"
        self.conflicts_dir.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute("PRAGMA foreign_keys = ON")

            # 1. Tasks table (habits/routines)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    uuid TEXT,
                    updated_at TEXT,
                    dirty INTEGER DEFAULT 0,
                    deleted INTEGER DEFAULT 0,
                    active INTEGER DEFAULT 1
                )
                """
            )

            # 2. Completions table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS completions (
                    task_id INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0,
                    uuid TEXT,
                    task_uuid TEXT,
                    completed_at TEXT,
                    updated_at TEXT,
                    dirty INTEGER DEFAULT 0,
                    deleted INTEGER DEFAULT 0,
                    PRIMARY KEY (task_id, date),
                    FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE
                )
                """
            )

            # 3. Journal entries table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS journal_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid TEXT UNIQUE,
                    date TEXT UNIQUE NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    word_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT,
                    dirty INTEGER DEFAULT 0,
                    deleted INTEGER DEFAULT 0
                )
                """
            )

            # 4. Outbox table for offline-first push sync
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    table_name TEXT NOT NULL,
                    record_uuid TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    attempts INTEGER DEFAULT 0,
                    last_error TEXT
                )
                """
            )

            # 5. Metadata table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

            # 6. Projects table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid TEXT UNIQUE,
                    title TEXT NOT NULL,
                    area TEXT NOT NULL DEFAULT 'Career',
                    status TEXT NOT NULL DEFAULT 'active',
                    outcome TEXT NOT NULL DEFAULT '',
                    deadline TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    archived_at TEXT,
                    dirty INTEGER DEFAULT 0,
                    deleted INTEGER DEFAULT 0
                )
                """
            )

            # 7. Actions table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid TEXT UNIQUE,
                    project_id INTEGER,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'next',
                    estimate_minutes INTEGER NOT NULL DEFAULT 30,
                    energy_level TEXT NOT NULL DEFAULT 'medium',
                    context TEXT NOT NULL DEFAULT 'desk',
                    due_date TEXT,
                    scheduled_date TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    dirty INTEGER DEFAULT 0,
                    deleted INTEGER DEFAULT 0,
                    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE SET NULL
                )
                """
            )

            # 8. Action Dependencies table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS action_dependencies (
                    action_id INTEGER NOT NULL,
                    blocked_by_action_id INTEGER NOT NULL,
                    PRIMARY KEY (action_id, blocked_by_action_id),
                    FOREIGN KEY (action_id) REFERENCES actions (id) ON DELETE CASCADE,
                    FOREIGN KEY (blocked_by_action_id) REFERENCES actions (id) ON DELETE CASCADE
                )
                """
            )

            # 9. Daily Priorities table (max 3 ranks per date constraint)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_priorities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid TEXT UNIQUE,
                    date TEXT NOT NULL,
                    action_id INTEGER NOT NULL,
                    rank INTEGER NOT NULL CHECK(rank BETWEEN 1 AND 3),
                    committed_at TEXT NOT NULL,
                    dirty INTEGER DEFAULT 0,
                    deleted INTEGER DEFAULT 0,
                    UNIQUE(date, rank),
                    FOREIGN KEY (action_id) REFERENCES actions (id) ON DELETE CASCADE
                )
                """
            )

            # 10. Time Blocks table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS time_blocks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid TEXT UNIQUE,
                    date TEXT NOT NULL,
                    starts_at TEXT NOT NULL,
                    ends_at TEXT NOT NULL,
                    action_id INTEGER,
                    kind TEXT NOT NULL DEFAULT 'deep_work',
                    planned_minutes INTEGER NOT NULL DEFAULT 90,
                    actual_minutes INTEGER,
                    status TEXT NOT NULL DEFAULT 'planned',
                    notes TEXT,
                    dirty INTEGER DEFAULT 0,
                    deleted INTEGER DEFAULT 0,
                    FOREIGN KEY (action_id) REFERENCES actions (id) ON DELETE SET NULL
                )
                """
            )

            # 11. Inbox Items table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS inbox_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid TEXT UNIQUE,
                    content TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'quick_capture',
                    status TEXT NOT NULL DEFAULT 'unprocessed',
                    linked_project_id INTEGER,
                    converted_action_id INTEGER,
                    resolved_at TEXT,
                    dirty INTEGER DEFAULT 0,
                    deleted INTEGER DEFAULT 0,
                    FOREIGN KEY (linked_project_id) REFERENCES projects (id) ON DELETE SET NULL,
                    FOREIGN KEY (converted_action_id) REFERENCES actions (id) ON DELETE SET NULL
                )
                """
            )

            # Run additive migrations on legacy tables
            self._migrate_existing_schema(conn)

            # Seed default routines if completely empty
            cur = conn.execute("SELECT COUNT(*) FROM tasks WHERE deleted = 0")
            if cur.fetchone()[0] == 0:
                now_iso = current_iso_time()
                for idx, title in enumerate(DEFAULT_ROUTINES):
                    t_uuid = generate_uuid()
                    conn.execute(
                        """
                        INSERT INTO tasks (title, sort_order, uuid, created_at, updated_at, dirty, deleted, active)
                        VALUES (?, ?, ?, ?, ?, 1, 0, 1)
                        """,
                        (title, idx, t_uuid, now_iso, now_iso),
                    )
                    self._enqueue_outbox(
                        conn,
                        "routine_tasks",
                        t_uuid,
                        "UPSERT",
                        {
                            "id": t_uuid,
                            "title": title,
                            "position": idx,
                            "active": True,
                            "created_at": now_iso,
                            "updated_at": now_iso,
                        },
                    )

            # Seed default projects & actions if empty
            cur_p = conn.execute("SELECT COUNT(*) FROM projects WHERE deleted = 0")
            if cur_p.fetchone()[0] == 0:
                self._seed_default_projects(conn)

            conn.commit()

    def _seed_default_projects(self, conn: sqlite3.Connection) -> None:
        """Seed default execution projects and actions."""
        now_iso = current_iso_time()
        today_str = datetime.date.today().strftime("%Y-%m-%d")

        created_action_ids: List[int] = []

        for p_data in DEFAULT_PROJECTS:
            p_uuid = generate_uuid()
            cur = conn.execute(
                """
                INSERT INTO projects (uuid, title, area, status, outcome, deadline, created_at, updated_at, dirty, deleted)
                VALUES (?, ?, ?, 'active', ?, NULL, ?, ?, 1, 0)
                """,
                (p_uuid, p_data["title"], p_data["area"], p_data["outcome"], now_iso, now_iso),
            )
            p_id = cur.lastrowid
            self._enqueue_outbox(
                conn,
                "projects",
                p_uuid,
                "UPSERT",
                {
                    "id": p_uuid,
                    "title": p_data["title"],
                    "area": p_data["area"],
                    "status": "active",
                    "outcome": p_data["outcome"],
                    "created_at": now_iso,
                    "updated_at": now_iso,
                },
            )

            for a_title, a_est, a_stat in p_data["actions"]:
                a_uuid = generate_uuid()
                cur_a = conn.execute(
                    """
                    INSERT INTO actions (uuid, project_id, title, status, estimate_minutes, energy_level, context, created_at, updated_at, dirty, deleted)
                    VALUES (?, ?, ?, ?, ?, 'medium', 'desk', ?, ?, 1, 0)
                    """,
                    (a_uuid, p_id, a_title, a_stat.value, a_est, now_iso, now_iso),
                )
                a_id = cur_a.lastrowid
                created_action_ids.append(a_id)
                self._enqueue_outbox(
                    conn,
                    "actions",
                    a_uuid,
                    "UPSERT",
                    {
                        "id": a_uuid,
                        "project_id": p_uuid,
                        "title": a_title,
                        "status": a_stat.value,
                        "estimate_minutes": a_est,
                        "created_at": now_iso,
                        "updated_at": now_iso,
                    },
                )

        # Seed Today's 3 Priorities for today if we have at least 3 actions
        if len(created_action_ids) >= 3:
            for rank, act_id in enumerate(created_action_ids[:3], start=1):
                dp_uuid = generate_uuid()
                conn.execute(
                    """
                    INSERT OR REPLACE INTO daily_priorities (uuid, date, action_id, rank, committed_at, dirty, deleted)
                    VALUES (?, ?, ?, ?, ?, 1, 0)
                    """,
                    (dp_uuid, today_str, act_id, rank, now_iso),
                )

            # Seed a planned focus block for today
            tb_uuid = generate_uuid()
            conn.execute(
                """
                INSERT INTO time_blocks (uuid, date, starts_at, ends_at, action_id, kind, planned_minutes, status, notes, dirty, deleted)
                VALUES (?, ?, '13:45', '15:15', ?, 'deep_work', 90, 'planned', 'Build lifeOS Planner MVP', 1, 0)
                """,
                (tb_uuid, today_str, created_action_ids[0]),
            )

    def _migrate_existing_schema(self, conn: sqlite3.Connection) -> None:
        """Additive migrations for existing databases."""
        task_cols = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "uuid" not in task_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN uuid TEXT")
        if "updated_at" not in task_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN updated_at TEXT")
        if "dirty" not in task_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN dirty INTEGER DEFAULT 0")
        if "deleted" not in task_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN deleted INTEGER DEFAULT 0")
        if "active" not in task_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN active INTEGER DEFAULT 1")

        cur = conn.execute("SELECT id, created_at FROM tasks WHERE uuid IS NULL OR uuid = ''")
        for row in cur.fetchall():
            u = generate_uuid()
            now_iso = current_iso_time()
            c_at = str(row["created_at"]) or now_iso
            conn.execute("UPDATE tasks SET uuid = ?, updated_at = ? WHERE id = ?", (u, c_at, row["id"]))

        comp_cols = {row["name"] for row in conn.execute("PRAGMA table_info(completions)").fetchall()}
        if "uuid" not in comp_cols:
            conn.execute("ALTER TABLE completions ADD COLUMN uuid TEXT")
        if "task_uuid" not in comp_cols:
            conn.execute("ALTER TABLE completions ADD COLUMN task_uuid TEXT")
        if "completed_at" not in comp_cols:
            conn.execute("ALTER TABLE completions ADD COLUMN completed_at TEXT")
        if "updated_at" not in comp_cols:
            conn.execute("ALTER TABLE completions ADD COLUMN updated_at TEXT")
        if "dirty" not in comp_cols:
            conn.execute("ALTER TABLE completions ADD COLUMN dirty INTEGER DEFAULT 0")
        if "deleted" not in comp_cols:
            conn.execute("ALTER TABLE completions ADD COLUMN deleted INTEGER DEFAULT 0")

        cur = conn.execute(
            """
            SELECT c.task_id, c.date, c.done, t.uuid as t_uuid
            FROM completions c
            JOIN tasks t ON c.task_id = t.id
            WHERE c.uuid IS NULL OR c.uuid = '' OR c.task_uuid IS NULL OR c.task_uuid = ''
            """
        )
        now_iso = current_iso_time()
        for row in cur.fetchall():
            u = generate_uuid()
            t_u = row["t_uuid"] or generate_uuid()
            conn.execute(
                """
                UPDATE completions
                SET uuid = ?, task_uuid = ?, completed_at = ?, updated_at = ?
                WHERE task_id = ? AND date = ?
                """,
                (u, t_u, now_iso, now_iso, row["task_id"], row["date"]),
            )

    def _enqueue_outbox(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        record_uuid: str,
        action: str,
        payload: Dict[str, Any],
    ) -> None:
        now_iso = current_iso_time()
        conn.execute(
            """
            INSERT INTO sync_outbox (table_name, record_uuid, action, payload, created_at, attempts, last_error)
            VALUES (?, ?, ?, ?, ?, 0, NULL)
            """,
            (table_name, record_uuid, action, json.dumps(payload), now_iso),
        )

    # -----------------------------------------------------------------------
    # Routine Tasks (Habits)
    # -----------------------------------------------------------------------

    def get_tasks(self) -> List[Task]:
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                SELECT id, title, sort_order, created_at, updated_at, uuid, active
                FROM tasks
                WHERE deleted = 0
                ORDER BY sort_order ASC, id ASC
                """
            )
            return [
                Task(
                    id=row["id"],
                    title=row["title"],
                    sort_order=row["sort_order"],
                    created_at=str(row["created_at"]),
                    updated_at=str(row["updated_at"] or ""),
                    uuid=row["uuid"] or generate_uuid(),
                    active=bool(row["active"]),
                )
                for row in cur.fetchall()
            ]

    def add_task(self, title: str) -> Task:
        title = title.strip()
        if not title:
            raise ValueError("Task title cannot be empty")
        now_iso = current_iso_time()
        t_uuid = generate_uuid()
        with self._get_conn() as conn:
            cur = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM tasks WHERE deleted = 0")
            next_order = cur.fetchone()[0]

            cur_ins = conn.execute(
                """
                INSERT INTO tasks (title, sort_order, uuid, created_at, updated_at, dirty, deleted, active)
                VALUES (?, ?, ?, ?, ?, 1, 0, 1)
                """,
                (title, next_order, t_uuid, now_iso, now_iso),
            )
            task_id = cur_ins.lastrowid

            self._enqueue_outbox(
                conn,
                "routine_tasks",
                t_uuid,
                "UPSERT",
                {
                    "id": t_uuid,
                    "title": title,
                    "position": next_order,
                    "active": True,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                },
            )
            conn.commit()
            return Task(
                id=task_id,
                title=title,
                sort_order=next_order,
                created_at=now_iso,
                updated_at=now_iso,
                uuid=t_uuid,
            )

    def update_task_title(self, task_id: int, title: str) -> None:
        title = title.strip()
        if not title:
            return
        now_iso = current_iso_time()
        with self._get_conn() as conn:
            cur = conn.execute("SELECT uuid, sort_order, created_at, active FROM tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()
            if not row:
                return
            t_uuid = row["uuid"]
            conn.execute(
                "UPDATE tasks SET title = ?, updated_at = ?, dirty = 1 WHERE id = ?",
                (title, now_iso, task_id),
            )
            self._enqueue_outbox(
                conn,
                "routine_tasks",
                t_uuid,
                "UPSERT",
                {
                    "id": t_uuid,
                    "title": title,
                    "position": row["sort_order"],
                    "active": bool(row["active"]),
                    "created_at": str(row["created_at"]),
                    "updated_at": now_iso,
                },
            )
            conn.commit()

    def delete_task(self, task_id: int) -> None:
        now_iso = current_iso_time()
        with self._get_conn() as conn:
            cur = conn.execute("SELECT uuid FROM tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()
            if not row:
                return
            t_uuid = row["uuid"]

            conn.execute("UPDATE tasks SET deleted = 1, updated_at = ?, dirty = 1 WHERE id = ?", (now_iso, task_id))
            conn.execute("DELETE FROM completions WHERE task_id = ?", (task_id,))

            cur = conn.execute("SELECT id, uuid, title, active, created_at FROM tasks WHERE deleted = 0 ORDER BY sort_order ASC, id ASC")
            rows = cur.fetchall()
            for idx, r in enumerate(rows):
                conn.execute("UPDATE tasks SET sort_order = ? WHERE id = ?", (idx, r["id"]))

            self._enqueue_outbox(
                conn,
                "routine_tasks",
                t_uuid,
                "DELETE",
                {"id": t_uuid, "active": False, "deleted": True, "updated_at": now_iso},
            )
            conn.commit()

    def restore_task(self, task_id: int) -> Optional[Task]:
        """Restore a soft-deleted task."""
        now_iso = current_iso_time()
        with self._get_conn() as conn:
            cur = conn.execute("SELECT uuid, title, created_at, active FROM tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()
            if not row:
                return None
            t_uuid = row["uuid"]
            title = row["title"]
            c_at = row["created_at"]

            c_ord = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM tasks WHERE deleted = 0").fetchone()
            next_order = c_ord[0] if c_ord else 0

            conn.execute(
                "UPDATE tasks SET deleted = 0, sort_order = ?, updated_at = ?, dirty = 1 WHERE id = ?",
                (next_order, now_iso, task_id),
            )
            self._enqueue_outbox(
                conn,
                "routine_tasks",
                t_uuid,
                "UPSERT",
                {
                    "id": t_uuid,
                    "title": title,
                    "position": next_order,
                    "active": bool(row["active"]),
                    "created_at": str(c_at),
                    "updated_at": now_iso,
                },
            )
            conn.commit()
            return Task(
                id=task_id,
                title=title,
                sort_order=next_order,
                created_at=str(c_at),
                updated_at=now_iso,
                uuid=t_uuid,
                active=bool(row["active"]),
            )

    def reorder_task(self, task_id: int, direction: int) -> None:
        tasks = self.get_tasks()
        idx = next((i for i, t in enumerate(tasks) if t.id == task_id), None)
        if idx is None:
            return
        target_idx = idx + direction
        if 0 <= target_idx < len(tasks):
            tasks[idx], tasks[target_idx] = tasks[target_idx], tasks[idx]
            now_iso = current_iso_time()
            with self._get_conn() as conn:
                for i, t in enumerate(tasks):
                    conn.execute("UPDATE tasks SET sort_order = ?, updated_at = ?, dirty = 1 WHERE id = ?", (i, now_iso, t.id))
                    self._enqueue_outbox(
                        conn,
                        "routine_tasks",
                        t.uuid,
                        "UPSERT",
                        {
                            "id": t.uuid,
                            "title": t.title,
                            "position": i,
                            "active": t.active,
                            "created_at": t.created_at,
                            "updated_at": now_iso,
                        },
                    )
                conn.commit()

    # -----------------------------------------------------------------------
    # Completions & Analytics
    # -----------------------------------------------------------------------

    def get_day_completions(self, date_str: str) -> Dict[int, Completion]:
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                SELECT c.task_id, c.date, c.done, c.uuid, c.task_uuid, c.completed_at, c.updated_at
                FROM completions c
                JOIN tasks t ON c.task_id = t.id
                WHERE c.date = ? AND t.deleted = 0
                """,
                (date_str,),
            )
            res = {}
            for row in cur.fetchall():
                res[row["task_id"]] = Completion(
                    task_id=row["task_id"],
                    date=row["date"],
                    done=bool(row["done"]),
                    uuid=row["uuid"] or generate_uuid(),
                    task_uuid=row["task_uuid"] or "",
                    completed_at=str(row["completed_at"] or ""),
                    updated_at=str(row["updated_at"] or ""),
                )
            return res

    def toggle_completion(self, task_id: int, date_str: str) -> bool:
        now_iso = current_iso_time()
        with self._get_conn() as conn:
            cur = conn.execute("SELECT uuid FROM tasks WHERE id = ?", (task_id,))
            t_row = cur.fetchone()
            if not t_row:
                return False
            task_uuid = t_row["uuid"]

            cur = conn.execute(
                "SELECT done, uuid, completed_at FROM completions WHERE task_id = ? AND date = ?",
                (task_id, date_str),
            )
            row = cur.fetchone()

            if row is None:
                new_done = 1
                c_uuid = generate_uuid()
                c_at = now_iso
                conn.execute(
                    """
                    INSERT INTO completions (task_id, date, done, uuid, task_uuid, completed_at, updated_at, dirty)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (task_id, date_str, new_done, c_uuid, task_uuid, c_at, now_iso),
                )
            else:
                new_done = 0 if row["done"] else 1
                c_uuid = row["uuid"] or generate_uuid()
                c_at = now_iso if new_done else str(row["completed_at"] or "")
                conn.execute(
                    """
                    UPDATE completions
                    SET done = ?, completed_at = ?, updated_at = ?, dirty = 1
                    WHERE task_id = ? AND date = ?
                    """,
                    (new_done, c_at, now_iso, task_id, date_str),
                )

            self._enqueue_outbox(
                conn,
                "completions",
                c_uuid,
                "UPSERT",
                {
                    "id": c_uuid,
                    "task_id": task_uuid,
                    "date": date_str,
                    "done": bool(new_done),
                    "completed_at": c_at if new_done else None,
                    "updated_at": now_iso,
                },
            )
            conn.commit()
            return bool(new_done)

    def calculate_streak(self, as_of_date: datetime.date) -> int:
        tasks = self.get_tasks()
        if not tasks:
            return 0
        req_count = len(tasks)

        streak = 0
        check_date = as_of_date
        today = datetime.date.today()

        with self._get_conn() as conn:
            if check_date == today:
                date_str = check_date.strftime("%Y-%m-%d")
                cur = conn.execute(
                    """
                    SELECT COUNT(*) FROM completions c
                    JOIN tasks t ON c.task_id = t.id
                    WHERE c.date = ? AND c.done = 1 AND t.deleted = 0
                    """,
                    (date_str,),
                )
                done_count = cur.fetchone()[0]
                if done_count >= req_count:
                    streak += 1
                check_date -= datetime.timedelta(days=1)

            while True:
                date_str = check_date.strftime("%Y-%m-%d")
                cur = conn.execute(
                    """
                    SELECT COUNT(*) FROM completions c
                    JOIN tasks t ON c.task_id = t.id
                    WHERE c.date = ? AND c.done = 1 AND t.deleted = 0
                    """,
                    (date_str,),
                )
                done_count = cur.fetchone()[0]
                if done_count >= req_count:
                    streak += 1
                    check_date -= datetime.timedelta(days=1)
                else:
                    break
        return streak

    def get_month_completion_stats(self, year: int, month: int) -> Dict[str, Tuple[int, int]]:
        num_days = calendar.monthrange(year, month)[1]
        start_date = f"{year:04d}-{month:02d}-01"
        end_date = f"{year:04d}-{month:02d}-{num_days:02d}"

        with self._get_conn() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM tasks WHERE deleted = 0")
            total_active_tasks = cur.fetchone()[0]

            cur = conn.execute(
                """
                SELECT c.date, COUNT(*) as done_count
                FROM completions c
                JOIN tasks t ON c.task_id = t.id
                WHERE c.date >= ? AND c.date <= ? AND c.done = 1 AND t.deleted = 0
                GROUP BY c.date
                """,
                (start_date, end_date),
            )
            rows = cur.fetchall()
            done_map = {row["date"]: row["done_count"] for row in rows}

        stats = {}
        for day in range(1, num_days + 1):
            d_str = f"{year:04d}-{month:02d}-{day:02d}"
            done = done_map.get(d_str, 0)
            stats[d_str] = (done, total_active_tasks)
        return stats

    def get_past_7_days_fractions(self, current_date: datetime.date) -> List[float]:
        tasks = self.get_tasks()
        total = len(tasks)
        if total == 0:
            return [0.0] * 7

        fractions = []
        for i in range(6, -1, -1):
            d = current_date - datetime.timedelta(days=i)
            d_str = d.strftime("%Y-%m-%d")
            comps = self.get_day_completions(d_str)
            done = sum(1 for c in comps.values() if c.done)
            fractions.append(min(1.0, done / total))
        return fractions

    # -----------------------------------------------------------------------
    # Projects CRUD & Invariants
    # -----------------------------------------------------------------------

    def get_projects(self, status: Optional[ProjectStatus] = None, include_actions: bool = True) -> List[Project]:
        with self._get_conn() as conn:
            query = "SELECT id, uuid, title, area, status, outcome, deadline, created_at, updated_at, archived_at FROM projects WHERE deleted = 0"
            params = []
            if status:
                query += " AND status = ?"
                params.append(status.value)
            query += " ORDER BY CASE status WHEN 'active' THEN 1 WHEN 'waiting' THEN 2 WHEN 'someday' THEN 3 ELSE 4 END, id ASC"

            cur = conn.execute(query, tuple(params))
            projects = []
            for row in cur.fetchall():
                p = Project(
                    id=row["id"],
                    uuid=row["uuid"] or generate_uuid(),
                    title=row["title"],
                    area=row["area"],
                    status=ProjectStatus(row["status"]),
                    outcome=row["outcome"] or "",
                    deadline=row["deadline"],
                    created_at=str(row["created_at"]),
                    updated_at=str(row["updated_at"]),
                    archived_at=row["archived_at"],
                )
                if include_actions:
                    p.actions = self.get_actions(project_id=p.id)
                projects.append(p)
            return projects

    def get_project(self, project_id: int) -> Optional[Project]:
        with self._get_conn() as conn:
            cur = conn.execute(
                "SELECT id, uuid, title, area, status, outcome, deadline, created_at, updated_at, archived_at FROM projects WHERE id = ? AND deleted = 0",
                (project_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            p = Project(
                id=row["id"],
                uuid=row["uuid"] or generate_uuid(),
                title=row["title"],
                area=row["area"],
                status=ProjectStatus(row["status"]),
                outcome=row["outcome"] or "",
                deadline=row["deadline"],
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
                archived_at=row["archived_at"],
            )
            p.actions = self.get_actions(project_id=p.id)
            return p

    def add_project(
        self,
        title: str,
        area: str = "Career",
        outcome: str = "",
        deadline: Optional[str] = None,
        initial_action_title: Optional[str] = None,
        initial_action_estimate: int = 30,
    ) -> Project:
        title = title.strip()
        if not title:
            raise ValueError("Project title cannot be empty.")

        # Invariant: Active project must always expose at least one concrete startable next action
        if initial_action_title:
            valid, hint = is_valid_physical_action(initial_action_title)
            if not valid:
                raise ValueError(f"Invalid initial action: {hint}")

        now_iso = current_iso_time()
        p_uuid = generate_uuid()

        with self._get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO projects (uuid, title, area, status, outcome, deadline, created_at, updated_at, dirty, deleted)
                VALUES (?, ?, ?, 'active', ?, ?, ?, ?, 1, 0)
                """,
                (p_uuid, title, area, outcome.strip(), deadline, now_iso, now_iso),
            )
            p_id = cur.lastrowid

            self._enqueue_outbox(
                conn,
                "projects",
                p_uuid,
                "UPSERT",
                {
                    "id": p_uuid,
                    "title": title,
                    "area": area,
                    "status": "active",
                    "outcome": outcome,
                    "deadline": deadline,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                },
            )
            conn.commit()

        # Add initial action if provided or default concrete step
        act_title = initial_action_title.strip() if initial_action_title else f"Define next milestone for {title}"
        self.add_action(
            title=act_title,
            project_id=p_id,
            status=ActionStatus.NEXT,
            estimate_minutes=max(15, initial_action_estimate),
        )

        return self.get_project(p_id)  # type: ignore

    def update_project(
        self,
        project_id: int,
        title: Optional[str] = None,
        area: Optional[str] = None,
        status: Optional[ProjectStatus] = None,
        outcome: Optional[str] = None,
        deadline: Optional[str] = None,
    ) -> Optional[Project]:
        now_iso = current_iso_time()
        with self._get_conn() as conn:
            cur = conn.execute("SELECT uuid, title, area, status, outcome, deadline FROM projects WHERE id = ? AND deleted = 0", (project_id,))
            row = cur.fetchone()
            if not row:
                return None
            p_uuid = row["uuid"]
            new_title = title.strip() if title is not None else row["title"]
            new_area = area.strip() if area is not None else row["area"]
            new_status = status.value if status is not None else row["status"]
            new_outcome = outcome.strip() if outcome is not None else row["outcome"]
            new_deadline = deadline if deadline is not None else row["deadline"]
            archived_at = now_iso if new_status == "archived" else None

            conn.execute(
                """
                UPDATE projects
                SET title = ?, area = ?, status = ?, outcome = ?, deadline = ?, archived_at = ?, updated_at = ?, dirty = 1
                WHERE id = ?
                """,
                (new_title, new_area, new_status, new_outcome, new_deadline, archived_at, now_iso, project_id),
            )
            self._enqueue_outbox(
                conn,
                "projects",
                p_uuid,
                "UPSERT",
                {
                    "id": p_uuid,
                    "title": new_title,
                    "area": new_area,
                    "status": new_status,
                    "outcome": new_outcome,
                    "deadline": new_deadline,
                    "updated_at": now_iso,
                },
            )
            conn.commit()
        return self.get_project(project_id)

    def delete_project(self, project_id: int) -> None:
        now_iso = current_iso_time()
        with self._get_conn() as conn:
            cur = conn.execute("SELECT uuid FROM projects WHERE id = ?", (project_id,))
            row = cur.fetchone()
            if not row:
                return
            p_uuid = row["uuid"]
            conn.execute("UPDATE projects SET deleted = 1, updated_at = ?, dirty = 1 WHERE id = ?", (now_iso, project_id))
            conn.execute("UPDATE actions SET deleted = 1, updated_at = ?, dirty = 1 WHERE project_id = ?", (now_iso, project_id))
            self._enqueue_outbox(
                conn,
                "projects",
                p_uuid,
                "DELETE",
                {"id": p_uuid, "deleted": True, "updated_at": now_iso},
            )
            conn.commit()

    def archive_project(self, project_id: int) -> None:
        self.update_project(project_id, status=ProjectStatus.ARCHIVED)

    # -----------------------------------------------------------------------
    # Actions CRUD & Dependencies
    # -----------------------------------------------------------------------

    def get_actions(
        self,
        project_id: Optional[int] = None,
        status: Optional[ActionStatus] = None,
    ) -> List[Action]:
        with self._get_conn() as conn:
            query = """
                SELECT a.id, a.uuid, a.project_id, a.title, a.status, a.estimate_minutes,
                       a.energy_level, a.context, a.due_date, a.scheduled_date, a.completed_at,
                       a.created_at, a.updated_at, p.title as project_title
                FROM actions a
                LEFT JOIN projects p ON a.project_id = p.id
                WHERE a.deleted = 0
            """
            params = []
            if project_id is not None:
                query += " AND a.project_id = ?"
                params.append(project_id)
            if status is not None:
                query += " AND a.status = ?"
                params.append(status.value)
            query += " ORDER BY a.id ASC"

            cur = conn.execute(query, tuple(params))
            rows = cur.fetchall()

            # Load dependencies for these actions
            action_ids = [r["id"] for r in rows]
            dep_map: Dict[int, List[int]] = {aid: [] for aid in action_ids}
            dep_title_map: Dict[int, List[str]] = {aid: [] for aid in action_ids}

            if action_ids:
                placeholders = ",".join("?" for _ in action_ids)
                cur_dep = conn.execute(
                    f"""
                    SELECT d.action_id, d.blocked_by_action_id, b.title as blocker_title
                    FROM action_dependencies d
                    JOIN actions b ON d.blocked_by_action_id = b.id
                    WHERE d.action_id IN ({placeholders}) AND b.deleted = 0 AND b.status != 'done'
                    """,
                    tuple(action_ids),
                )
                for d_row in cur_dep.fetchall():
                    dep_map[d_row["action_id"]].append(d_row["blocked_by_action_id"])
                    dep_title_map[d_row["action_id"]].append(d_row["blocker_title"])

            actions = []
            for r in rows:
                aid = r["id"]
                actions.append(
                    Action(
                        id=aid,
                        uuid=r["uuid"] or generate_uuid(),
                        project_id=r["project_id"],
                        title=r["title"],
                        status=ActionStatus(r["status"]),
                        estimate_minutes=r["estimate_minutes"],
                        energy_level=EnergyLevel(r["energy_level"] or "medium"),
                        context=r["context"] or "desk",
                        due_date=r["due_date"],
                        scheduled_date=r["scheduled_date"],
                        completed_at=r["completed_at"],
                        created_at=str(r["created_at"]),
                        updated_at=str(r["updated_at"]),
                        project_title=r["project_title"],
                        blocked_by=dep_map.get(aid, []),
                        blocker_titles=dep_title_map.get(aid, []),
                    )
                )
            return actions

    def get_action(self, action_id: int) -> Optional[Action]:
        actions = self.get_actions()
        return next((a for a in actions if a.id == action_id), None)

    def add_action(
        self,
        title: str,
        project_id: Optional[int] = None,
        status: ActionStatus = ActionStatus.NEXT,
        estimate_minutes: int = 30,
        energy_level: EnergyLevel = EnergyLevel.MEDIUM,
        context: str = "desk",
        due_date: Optional[str] = None,
        scheduled_date: Optional[str] = None,
    ) -> Action:
        valid, hint = is_valid_physical_action(title)
        if not valid:
            raise ValueError(hint)

        if estimate_minutes <= 0:
            estimate_minutes = 30

        now_iso = current_iso_time()
        a_uuid = generate_uuid()

        with self._get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO actions (
                    uuid, project_id, title, status, estimate_minutes,
                    energy_level, context, due_date, scheduled_date,
                    created_at, updated_at, dirty, deleted
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
                """,
                (
                    a_uuid,
                    project_id,
                    title.strip(),
                    status.value,
                    estimate_minutes,
                    energy_level.value,
                    context.strip(),
                    due_date,
                    scheduled_date,
                    now_iso,
                    now_iso,
                ),
            )
            action_id = cur.lastrowid

            self._enqueue_outbox(
                conn,
                "actions",
                a_uuid,
                "UPSERT",
                {
                    "id": a_uuid,
                    "project_id": project_id,
                    "title": title.strip(),
                    "status": status.value,
                    "estimate_minutes": estimate_minutes,
                    "energy_level": energy_level.value,
                    "context": context,
                    "due_date": due_date,
                    "scheduled_date": scheduled_date,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                },
            )
            conn.commit()

        return self.get_action(action_id)  # type: ignore

    def update_action(
        self,
        action_id: int,
        title: Optional[str] = None,
        project_id: Optional[int] = None,
        status: Optional[ActionStatus] = None,
        estimate_minutes: Optional[int] = None,
        energy_level: Optional[EnergyLevel] = None,
        context: Optional[str] = None,
        due_date: Optional[str] = None,
        scheduled_date: Optional[str] = None,
    ) -> Optional[Action]:
        now_iso = current_iso_time()
        with self._get_conn() as conn:
            cur = conn.execute("SELECT * FROM actions WHERE id = ? AND deleted = 0", (action_id,))
            row = cur.fetchone()
            if not row:
                return None
            a_uuid = row["uuid"]

            new_title = title.strip() if title is not None else row["title"]
            if title is not None:
                valid, hint = is_valid_physical_action(new_title)
                if not valid:
                    raise ValueError(hint)

            new_proj = project_id if project_id is not None else row["project_id"]
            new_stat = status.value if status is not None else row["status"]
            new_est = estimate_minutes if estimate_minutes is not None else row["estimate_minutes"]
            new_energy = energy_level.value if energy_level is not None else row["energy_level"]
            new_ctx = context.strip() if context is not None else row["context"]
            new_due = due_date if due_date is not None else row["due_date"]
            new_sched = scheduled_date if scheduled_date is not None else row["scheduled_date"]
            completed_at = now_iso if new_stat == "done" else (None if new_stat != "done" and row["status"] == "done" else row["completed_at"])

            conn.execute(
                """
                UPDATE actions
                SET title = ?, project_id = ?, status = ?, estimate_minutes = ?,
                    energy_level = ?, context = ?, due_date = ?, scheduled_date = ?,
                    completed_at = ?, updated_at = ?, dirty = 1
                WHERE id = ?
                """,
                (
                    new_title,
                    new_proj,
                    new_stat,
                    new_est,
                    new_energy,
                    new_ctx,
                    new_due,
                    new_sched,
                    completed_at,
                    now_iso,
                    action_id,
                ),
            )
            self._enqueue_outbox(
                conn,
                "actions",
                a_uuid,
                "UPSERT",
                {
                    "id": a_uuid,
                    "title": new_title,
                    "project_id": new_proj,
                    "status": new_stat,
                    "estimate_minutes": new_est,
                    "energy_level": new_energy,
                    "context": new_ctx,
                    "due_date": new_due,
                    "scheduled_date": new_sched,
                    "completed_at": completed_at,
                    "updated_at": now_iso,
                },
            )
            conn.commit()
        return self.get_action(action_id)

    def delete_action(self, action_id: int) -> None:
        now_iso = current_iso_time()
        with self._get_conn() as conn:
            cur = conn.execute("SELECT uuid FROM actions WHERE id = ?", (action_id,))
            row = cur.fetchone()
            if not row:
                return
            a_uuid = row["uuid"]
            conn.execute("UPDATE actions SET deleted = 1, updated_at = ?, dirty = 1 WHERE id = ?", (now_iso, action_id))
            conn.execute("DELETE FROM daily_priorities WHERE action_id = ?", (action_id,))
            conn.execute("DELETE FROM action_dependencies WHERE action_id = ? OR blocked_by_action_id = ?", (action_id, action_id))
            self._enqueue_outbox(
                conn,
                "actions",
                a_uuid,
                "DELETE",
                {"id": a_uuid, "deleted": True, "updated_at": now_iso},
            )
            conn.commit()

    def set_action_status(self, action_id: int, status: ActionStatus) -> None:
        self.update_action(action_id, status=status)

    def add_action_dependency(self, action_id: int, blocked_by_id: int) -> None:
        if action_id == blocked_by_id:
            return
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO action_dependencies (action_id, blocked_by_action_id) VALUES (?, ?)",
                (action_id, blocked_by_id),
            )
            # Update action status to WAITING
            conn.execute("UPDATE actions SET status = 'waiting' WHERE id = ? AND status = 'next'", (action_id,))
            conn.commit()

    def remove_action_dependency(self, action_id: int, blocked_by_id: int) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM action_dependencies WHERE action_id = ? AND blocked_by_action_id = ?",
                (action_id, blocked_by_id),
            )
            conn.commit()

    def get_unblocked_next_actions(self) -> List[Action]:
        actions = self.get_actions(status=ActionStatus.NEXT)
        return [a for a in actions if not a.is_blocked]

    # -----------------------------------------------------------------------
    # Daily Priorities (Constraint: at most 3 per date, requires estimate & title)
    # -----------------------------------------------------------------------

    def get_daily_priorities(self, date_str: str) -> List[DailyPriority]:
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                SELECT dp.id, dp.uuid, dp.date, dp.action_id, dp.rank, dp.committed_at
                FROM daily_priorities dp
                JOIN actions a ON dp.action_id = a.id
                WHERE dp.date = ? AND dp.deleted = 0 AND a.deleted = 0
                ORDER BY dp.rank ASC
                """,
                (date_str,),
            )
            priorities = []
            for r in cur.fetchall():
                act = self.get_action(r["action_id"])
                priorities.append(
                    DailyPriority(
                        id=r["id"],
                        uuid=r["uuid"] or generate_uuid(),
                        date=r["date"],
                        action_id=r["action_id"],
                        rank=r["rank"],
                        committed_at=str(r["committed_at"]),
                        action=act,
                    )
                )
            return priorities

    def set_daily_priority(self, date_str: str, rank: int, action_id: int) -> DailyPriority:
        if rank not in (1, 2, 3):
            raise ValueError("Daily priorities allows at most 3 ranks (rank must be 1, 2, or 3).")

        act = self.get_action(action_id)
        if not act:
            raise ValueError(f"Action #{action_id} not found.")

        if act.estimate_minutes <= 0:
            raise ValueError("A priority cannot be committed without an estimate_minutes > 0.")

        valid, hint = is_valid_physical_action(act.title)
        if not valid:
            raise ValueError(f"A priority cannot be committed with vague action: {hint}")

        now_iso = current_iso_time()
        dp_uuid = generate_uuid()

        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO daily_priorities (uuid, date, action_id, rank, committed_at, dirty, deleted)
                VALUES (?, ?, ?, ?, ?, 1, 0)
                ON CONFLICT(date, rank) DO UPDATE SET
                    action_id = excluded.action_id,
                    committed_at = excluded.committed_at,
                    dirty = 1,
                    deleted = 0
                """,
                (dp_uuid, date_str, action_id, rank, now_iso),
            )
            self._enqueue_outbox(
                conn,
                "daily_priorities",
                dp_uuid,
                "UPSERT",
                {
                    "id": dp_uuid,
                    "date": date_str,
                    "action_id": act.uuid,
                    "rank": rank,
                    "committed_at": now_iso,
                },
            )
            conn.commit()

        return DailyPriority(
            id=rank,
            uuid=dp_uuid,
            date=date_str,
            action_id=action_id,
            rank=rank,
            committed_at=now_iso,
            action=act,
        )

    def remove_daily_priority(self, date_str: str, rank: int) -> None:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM daily_priorities WHERE date = ? AND rank = ?", (date_str, rank))
            conn.commit()

    # -----------------------------------------------------------------------
    # Time Blocks (Operational Day Schedule & Focus)
    # -----------------------------------------------------------------------

    def get_time_blocks(self, date_str: str) -> List[TimeBlock]:
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                SELECT tb.id, tb.uuid, tb.date, tb.starts_at, tb.ends_at, tb.action_id,
                       tb.kind, tb.planned_minutes, tb.actual_minutes, tb.status, tb.notes
                FROM time_blocks tb
                WHERE tb.date = ? AND tb.deleted = 0
                ORDER BY tb.starts_at ASC
                """,
                (date_str,),
            )
            blocks = []
            for r in cur.fetchall():
                act = self.get_action(r["action_id"]) if r["action_id"] else None
                blocks.append(
                    TimeBlock(
                        id=r["id"],
                        uuid=r["uuid"] or generate_uuid(),
                        date=r["date"],
                        starts_at=r["starts_at"],
                        ends_at=r["ends_at"],
                        action_id=r["action_id"],
                        kind=BlockKind(r["kind"]),
                        planned_minutes=r["planned_minutes"],
                        actual_minutes=r["actual_minutes"],
                        status=BlockStatus(r["status"]),
                        notes=r["notes"],
                        action=act,
                    )
                )
            return blocks

    def add_time_block(
        self,
        date_str: str,
        starts_at: str,
        ends_at: str,
        action_id: Optional[int] = None,
        kind: BlockKind = BlockKind.DEEP_WORK,
        planned_minutes: int = 90,
        notes: Optional[str] = None,
    ) -> TimeBlock:
        tb_uuid = generate_uuid()
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO time_blocks (
                    uuid, date, starts_at, ends_at, action_id, kind,
                    planned_minutes, actual_minutes, status, notes, dirty, deleted
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'planned', ?, 1, 0)
                """,
                (
                    tb_uuid,
                    date_str,
                    starts_at.strip(),
                    ends_at.strip(),
                    action_id,
                    kind.value,
                    planned_minutes,
                    notes,
                ),
            )
            block_id = cur.lastrowid
            self._enqueue_outbox(
                conn,
                "time_blocks",
                tb_uuid,
                "UPSERT",
                {
                    "id": tb_uuid,
                    "date": date_str,
                    "starts_at": starts_at,
                    "ends_at": ends_at,
                    "action_id": action_id,
                    "kind": kind.value,
                    "planned_minutes": planned_minutes,
                    "status": "planned",
                    "notes": notes,
                },
            )
            conn.commit()

        act = self.get_action(action_id) if action_id else None
        return TimeBlock(
            id=block_id,
            uuid=tb_uuid,
            date=date_str,
            starts_at=starts_at,
            ends_at=ends_at,
            action_id=action_id,
            kind=kind,
            planned_minutes=planned_minutes,
            status=BlockStatus.PLANNED,
            notes=notes,
            action=act,
        )

    def update_time_block(
        self,
        block_id: int,
        starts_at: Optional[str] = None,
        ends_at: Optional[str] = None,
        action_id: Optional[int] = None,
        kind: Optional[BlockKind] = None,
        planned_minutes: Optional[int] = None,
        actual_minutes: Optional[int] = None,
        status: Optional[BlockStatus] = None,
        notes: Optional[str] = None,
    ) -> Optional[TimeBlock]:
        with self._get_conn() as conn:
            cur = conn.execute("SELECT * FROM time_blocks WHERE id = ? AND deleted = 0", (block_id,))
            row = cur.fetchone()
            if not row:
                return None
            tb_uuid = row["uuid"]
            new_starts = starts_at if starts_at is not None else row["starts_at"]
            new_ends = ends_at if ends_at is not None else row["ends_at"]
            new_act = action_id if action_id is not None else row["action_id"]
            new_kind = kind.value if kind is not None else row["kind"]
            new_plan = planned_minutes if planned_minutes is not None else row["planned_minutes"]
            new_actual = actual_minutes if actual_minutes is not None else row["actual_minutes"]
            new_status = status.value if status is not None else row["status"]
            new_notes = notes if notes is not None else row["notes"]

            conn.execute(
                """
                UPDATE time_blocks
                SET starts_at = ?, ends_at = ?, action_id = ?, kind = ?,
                    planned_minutes = ?, actual_minutes = ?, status = ?, notes = ?, dirty = 1
                WHERE id = ?
                """,
                (new_starts, new_ends, new_act, new_kind, new_plan, new_actual, new_status, new_notes, block_id),
            )
            self._enqueue_outbox(
                conn,
                "time_blocks",
                tb_uuid,
                "UPSERT",
                {
                    "id": tb_uuid,
                    "date": row["date"],
                    "starts_at": new_starts,
                    "ends_at": new_ends,
                    "action_id": new_act,
                    "kind": new_kind,
                    "planned_minutes": new_plan,
                    "actual_minutes": new_actual,
                    "status": new_status,
                    "notes": new_notes,
                },
            )
            conn.commit()

        act = self.get_action(new_act) if new_act else None
        return TimeBlock(
            id=block_id,
            uuid=tb_uuid,
            date=row["date"],
            starts_at=new_starts,
            ends_at=new_ends,
            action_id=new_act,
            kind=BlockKind(new_kind),
            planned_minutes=new_plan,
            actual_minutes=new_actual,
            status=BlockStatus(new_status),
            notes=new_notes,
            action=act,
        )

    def delete_time_block(self, block_id: int) -> None:
        with self._get_conn() as conn:
            cur = conn.execute("SELECT uuid FROM time_blocks WHERE id = ?", (block_id,))
            row = cur.fetchone()
            if not row:
                return
            tb_uuid = row["uuid"]
            conn.execute("UPDATE time_blocks SET deleted = 1, dirty = 1 WHERE id = ?", (block_id,))
            self._enqueue_outbox(
                conn,
                "time_blocks",
                tb_uuid,
                "DELETE",
                {"id": tb_uuid, "deleted": True},
            )
            conn.commit()

    def close_time_block(
        self,
        block_id: int,
        status: BlockStatus,
        actual_minutes: int,
        notes: Optional[str] = None,
    ) -> Optional[TimeBlock]:
        """Close a focus block with actual outcome."""
        return self.update_time_block(
            block_id,
            status=status,
            actual_minutes=actual_minutes,
            notes=notes,
        )

    # -----------------------------------------------------------------------
    # Command Center & Capacity Helpers
    # -----------------------------------------------------------------------

    def get_now_card(self, date_str: str, current_time_str: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Rule: Exactly ONE Now card, ever.
        Priority:
        1. An active or current/next scheduled time block for today.
        2. Top uncompleted Daily Priority for today.
        3. Top unblocked NEXT action from an active project.
        """
        blocks = self.get_time_blocks(date_str)
        now_t = current_time_str or datetime.datetime.now().strftime("%H:%M")

        # 1. Look for currently active block or upcoming planned block
        for b in blocks:
            if b.status == BlockStatus.ACTIVE:
                return {
                    "type": "block",
                    "id": b.id,
                    "title": b.action.title if b.action else (b.notes or "Deep Focus Block"),
                    "project_title": b.action.project_title if b.action else "Focus",
                    "time_window": f"{b.starts_at}–{b.ends_at}",
                    "minutes": b.planned_minutes,
                    "is_active": True,
                    "action_id": b.action_id,
                    "block_id": b.id,
                }
            if b.status == BlockStatus.PLANNED and b.starts_at <= now_t <= b.ends_at:
                return {
                    "type": "block",
                    "id": b.id,
                    "title": b.action.title if b.action else (b.notes or "Scheduled Block"),
                    "project_title": b.action.project_title if b.action else "Focus",
                    "time_window": f"{b.starts_at}–{b.ends_at}",
                    "minutes": b.planned_minutes,
                    "is_active": False,
                    "action_id": b.action_id,
                    "block_id": b.id,
                }

        # Upcoming planned block today
        upcoming = [b for b in blocks if b.status == BlockStatus.PLANNED and b.starts_at > now_t]
        if upcoming:
            b = upcoming[0]
            return {
                "type": "block",
                "id": b.id,
                "title": b.action.title if b.action else (b.notes or "Upcoming Block"),
                "project_title": b.action.project_title if b.action else "Focus",
                "time_window": f"{b.starts_at}–{b.ends_at}",
                "minutes": b.planned_minutes,
                "is_active": False,
                "action_id": b.action_id,
                "block_id": b.id,
            }

        # 2. Look for top uncompleted daily priority
        priorities = self.get_daily_priorities(date_str)
        for p in priorities:
            if p.action and p.action.status != ActionStatus.DONE:
                return {
                    "type": "priority",
                    "id": p.action.id,
                    "title": p.action.title,
                    "project_title": p.action.project_title or "Priority",
                    "time_window": f"Rank #{p.rank}",
                    "minutes": p.action.estimate_minutes,
                    "is_active": False,
                    "action_id": p.action.id,
                    "block_id": None,
                }

        # 3. Top unblocked next action from active projects
        unblocked = self.get_unblocked_next_actions()
        if unblocked:
            a = unblocked[0]
            return {
                "type": "action",
                "id": a.id,
                "title": a.title,
                "project_title": a.project_title or "Next Action",
                "time_window": "Next Up",
                "minutes": a.estimate_minutes,
                "is_active": False,
                "action_id": a.id,
                "block_id": None,
            }

        return None

    def get_day_capacity_budget(self, date_str: str, capacity_minutes: int = 210) -> Dict[str, Any]:
        """
        Deep-work capacity budget (default 3h30m = 210m).
        Computes planned minutes, available minutes, and overcommitted warning.
        """
        blocks = self.get_time_blocks(date_str)
        planned_deep_work = sum(
            b.planned_minutes for b in blocks if b.kind == BlockKind.DEEP_WORK and b.status != BlockStatus.SKIPPED
        )

        priorities = self.get_daily_priorities(date_str)
        # If no blocks yet, compute from priorities
        if not blocks and priorities:
            planned_deep_work = sum(
                p.action.estimate_minutes for p in priorities if p.action and p.action.status != ActionStatus.DONE
            )

        available_minutes = max(0, capacity_minutes - planned_deep_work)
        overcommitted = planned_deep_work > capacity_minutes

        return {
            "capacity_minutes": capacity_minutes,
            "planned_minutes": planned_deep_work,
            "available_minutes": available_minutes,
            "overcommitted": overcommitted,
            "planned_str": f"{planned_deep_work // 60}h {planned_deep_work % 60:02d}m",
            "available_str": f"{available_minutes // 60}h {available_minutes % 60:02d}m",
            "capacity_str": f"{capacity_minutes // 60}h {capacity_minutes % 60:02d}m",
        }

    # -----------------------------------------------------------------------
    # Global Quick Capture & Inbox
    # -----------------------------------------------------------------------

    def get_inbox_items(self, status: InboxStatus = InboxStatus.UNPROCESSED) -> List[InboxItem]:
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                SELECT id, uuid, content, captured_at, source, status, linked_project_id, converted_action_id, resolved_at
                FROM inbox_items
                WHERE status = ? AND deleted = 0
                ORDER BY id DESC
                """,
                (status.value,),
            )
            return [
                InboxItem(
                    id=row["id"],
                    uuid=row["uuid"] or generate_uuid(),
                    content=row["content"],
                    captured_at=str(row["captured_at"]),
                    source=row["source"],
                    status=InboxStatus(row["status"]),
                    linked_project_id=row["linked_project_id"],
                    converted_action_id=row["converted_action_id"],
                    resolved_at=row["resolved_at"],
                )
                for row in cur.fetchall()
            ]

    def add_inbox_item(self, content: str, source: str = "quick_capture") -> InboxItem:
        content = content.strip()
        if not content:
            raise ValueError("Inbox item content cannot be empty.")

        now_iso = current_iso_time()
        i_uuid = generate_uuid()

        with self._get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO inbox_items (uuid, content, captured_at, source, status, dirty, deleted)
                VALUES (?, ?, ?, ?, 'unprocessed', 1, 0)
                """,
                (i_uuid, content, now_iso, source),
            )
            inbox_id = cur.lastrowid
            self._enqueue_outbox(
                conn,
                "inbox_items",
                i_uuid,
                "UPSERT",
                {
                    "id": i_uuid,
                    "content": content,
                    "captured_at": now_iso,
                    "source": source,
                    "status": "unprocessed",
                },
            )
            conn.commit()

        return InboxItem(
            id=inbox_id,
            uuid=i_uuid,
            content=content,
            captured_at=now_iso,
            source=source,
            status=InboxStatus.UNPROCESSED,
        )

    def convert_inbox_to_action(
        self,
        inbox_id: int,
        title: str,
        project_id: Optional[int] = None,
        estimate_minutes: int = 30,
    ) -> Action:
        action = self.add_action(
            title=title,
            project_id=project_id,
            status=ActionStatus.NEXT,
            estimate_minutes=estimate_minutes,
        )
        now_iso = current_iso_time()
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE inbox_items
                SET status = 'converted', converted_action_id = ?, linked_project_id = ?, resolved_at = ?, dirty = 1
                WHERE id = ?
                """,
                (action.id, project_id, now_iso, inbox_id),
            )
            conn.commit()
        return action

    def convert_inbox_to_project(
        self,
        inbox_id: int,
        title: str,
        area: str = "Career",
        outcome: str = "",
        initial_action: str = "",
    ) -> Project:
        project = self.add_project(
            title=title,
            area=area,
            outcome=outcome,
            initial_action_title=initial_action or f"Outline next steps for {title}",
        )
        now_iso = current_iso_time()
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE inbox_items
                SET status = 'converted', linked_project_id = ?, resolved_at = ?, dirty = 1
                WHERE id = ?
                """,
                (project.id, now_iso, inbox_id),
            )
            conn.commit()
        return project

    def resolve_inbox_item(self, inbox_id: int, status: InboxStatus = InboxStatus.ARCHIVED) -> None:
        now_iso = current_iso_time()
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE inbox_items SET status = ?, resolved_at = ?, dirty = 1 WHERE id = ?",
                (status.value, now_iso, inbox_id),
            )
            conn.commit()

    # -----------------------------------------------------------------------
    # Journal Operations (Dual-Mirrored Plain Text + SQLite)
    # -----------------------------------------------------------------------

    def get_journal_file_path(self, date_str: str) -> Path:
        return self.journal_dir / f"{date_str}.txt"

    def get_journal_entry(self, date_str: str) -> Optional[JournalEntry]:
        file_path = self.get_journal_file_path(date_str)
        file_content: Optional[str] = None
        file_mtime: float = 0.0

        if file_path.exists():
            try:
                file_content = file_path.read_text(encoding="utf-8")
                file_mtime = file_path.stat().st_mtime
            except Exception:
                pass

        with self._get_conn() as conn:
            cur = conn.execute(
                """
                SELECT id, uuid, date, content, word_count, created_at, updated_at, dirty, deleted
                FROM journal_entries
                WHERE date = ? AND deleted = 0
                """,
                (date_str,),
            )
            db_row = cur.fetchone()

            if file_content is not None and db_row is not None:
                db_content = db_row["content"]
                if file_content != db_content:
                    now_iso = current_iso_time()
                    w_count = len(file_content.split()) if file_content else 0
                    j_uuid = db_row["uuid"] or generate_uuid()
                    conn.execute(
                        """
                        UPDATE journal_entries
                        SET content = ?, word_count = ?, updated_at = ?, dirty = 1
                        WHERE date = ?
                        """,
                        (file_content, w_count, now_iso, date_str),
                    )
                    self._enqueue_outbox(
                        conn,
                        "journal_entries",
                        j_uuid,
                        "UPSERT",
                        {
                            "id": j_uuid,
                            "date": date_str,
                            "content": file_content,
                            "word_count": w_count,
                            "updated_at": now_iso,
                        },
                    )
                    conn.commit()
                    return JournalEntry(
                        id=db_row["id"],
                        uuid=j_uuid,
                        date=date_str,
                        content=file_content,
                        word_count=w_count,
                        created_at=str(db_row["created_at"]),
                        updated_at=now_iso,
                        mtime=file_mtime,
                    )
                else:
                    return JournalEntry(
                        id=db_row["id"],
                        uuid=db_row["uuid"] or generate_uuid(),
                        date=date_str,
                        content=db_row["content"],
                        word_count=db_row["word_count"],
                        created_at=str(db_row["created_at"]),
                        updated_at=str(db_row["updated_at"]),
                        mtime=file_mtime,
                    )

            elif file_content is not None and db_row is None:
                if not file_content.strip():
                    return None
                now_iso = current_iso_time()
                j_uuid = generate_uuid()
                w_count = len(file_content.split())
                cur = conn.execute(
                    """
                    INSERT INTO journal_entries (uuid, date, content, word_count, created_at, updated_at, dirty, deleted)
                    VALUES (?, ?, ?, ?, ?, ?, 1, 0)
                    """,
                    (j_uuid, date_str, file_content, w_count, now_iso, now_iso),
                )
                j_id = cur.lastrowid
                self._enqueue_outbox(
                    conn,
                    "journal_entries",
                    j_uuid,
                    "UPSERT",
                    {
                        "id": j_uuid,
                        "date": date_str,
                        "content": file_content,
                        "word_count": w_count,
                        "created_at": now_iso,
                        "updated_at": now_iso,
                    },
                )
                conn.commit()
                return JournalEntry(
                    id=j_id,
                    uuid=j_uuid,
                    date=date_str,
                    content=file_content,
                    word_count=w_count,
                    created_at=now_iso,
                    updated_at=now_iso,
                    mtime=file_mtime,
                )

            elif file_content is None and db_row is not None:
                if not db_row["content"].strip():
                    return None
                try:
                    file_path.write_text(db_row["content"], encoding="utf-8")
                    file_mtime = file_path.stat().st_mtime
                except Exception:
                    pass
                return JournalEntry(
                    id=db_row["id"],
                    uuid=db_row["uuid"] or generate_uuid(),
                    date=date_str,
                    content=db_row["content"],
                    word_count=db_row["word_count"],
                    created_at=str(db_row["created_at"]),
                    updated_at=str(db_row["updated_at"]),
                    mtime=file_mtime,
                )

        return None

    def save_journal_entry(
        self,
        date_str: str,
        content: str,
        expected_mtime: Optional[float] = None,
    ) -> Tuple[JournalEntry, bool]:
        file_path = self.get_journal_file_path(date_str)
        is_collision = False

        if expected_mtime is not None and file_path.exists():
            current_mtime = file_path.stat().st_mtime
            if abs(current_mtime - expected_mtime) > 0.001:
                is_collision = True

        file_path.write_text(content, encoding="utf-8")
        new_mtime = file_path.stat().st_mtime

        now_iso = current_iso_time()
        w_count = len(content.split()) if content else 0

        with self._get_conn() as conn:
            cur = conn.execute("SELECT id, uuid, created_at FROM journal_entries WHERE date = ?", (date_str,))
            row = cur.fetchone()

            if row is None:
                j_uuid = generate_uuid()
                cur = conn.execute(
                    """
                    INSERT INTO journal_entries (uuid, date, content, word_count, created_at, updated_at, dirty, deleted)
                    VALUES (?, ?, ?, ?, ?, ?, 1, 0)
                    """,
                    (j_uuid, date_str, content, w_count, now_iso, now_iso),
                )
                j_id = cur.lastrowid
                c_at = now_iso
            else:
                j_id = row["id"]
                j_uuid = row["uuid"] or generate_uuid()
                c_at = str(row["created_at"])
                conn.execute(
                    """
                    UPDATE journal_entries
                    SET content = ?, word_count = ?, updated_at = ?, dirty = 1, deleted = 0
                    WHERE date = ?
                    """,
                    (content, w_count, now_iso, date_str),
                )

            self._enqueue_outbox(
                conn,
                "journal_entries",
                j_uuid,
                "UPSERT",
                {
                    "id": j_uuid,
                    "date": date_str,
                    "content": content,
                    "word_count": w_count,
                    "created_at": c_at,
                    "updated_at": now_iso,
                },
            )
            conn.commit()

        return (
            JournalEntry(
                id=j_id,
                uuid=j_uuid,
                date=date_str,
                content=content,
                word_count=w_count,
                created_at=c_at,
                updated_at=now_iso,
                mtime=new_mtime,
            ),
            is_collision,
        )

    def delete_journal_entry(self, date_str: str) -> None:
        file_path = self.get_journal_file_path(date_str)
        if file_path.exists():
            try:
                file_path.unlink()
            except Exception:
                pass

        now_iso = current_iso_time()
        with self._get_conn() as conn:
            cur = conn.execute("SELECT uuid FROM journal_entries WHERE date = ?", (date_str,))
            row = cur.fetchone()
            if row:
                j_uuid = row["uuid"]
                conn.execute(
                    """
                    UPDATE journal_entries
                    SET deleted = 1, content = '', word_count = 0, updated_at = ?, dirty = 1
                    WHERE date = ?
                    """,
                    (now_iso, date_str),
                )
                self._enqueue_outbox(
                    conn,
                    "journal_entries",
                    j_uuid,
                    "DELETE",
                    {"id": j_uuid, "date": date_str, "deleted": True, "updated_at": now_iso},
                )
                conn.commit()

    def list_journal_entries(self) -> List[JournalEntry]:
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                SELECT id, uuid, date, content, word_count, created_at, updated_at
                FROM journal_entries
                WHERE deleted = 0 AND length(trim(content)) > 0
                ORDER BY date DESC
                """
            )
            return [
                JournalEntry(
                    id=row["id"],
                    uuid=row["uuid"],
                    date=row["date"],
                    content=row["content"],
                    word_count=row["word_count"],
                    created_at=str(row["created_at"]),
                    updated_at=str(row["updated_at"]),
                )
                for row in cur.fetchall()
            ]

    def get_dates_with_journals(self, start_date: str, end_date: str) -> Set[str]:
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                SELECT date FROM journal_entries
                WHERE date >= ? AND date <= ? AND deleted = 0 AND length(trim(content)) > 0
                """,
                (start_date, end_date),
            )
            return {row["date"] for row in cur.fetchall()}
