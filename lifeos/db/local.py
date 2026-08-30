"""
lifeOS Local Persistence Layer
==============================
SQLite storage with schema migrations, outbox queue for cloud sync,
and dual-mirrored plain text journal files (~/.lifeos/journal/YYYY-MM-DD.txt).
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
    Completion,
    JournalEntry,
    Task,
    current_iso_time,
    generate_uuid,
)

DEFAULT_ROUTINES = [
    "Morning sunlight + Hydration (500ml)",
    "Deep focus session (90 mins)",
    "Zone 2 Cardio or Strength workout",
    "Read 15 pages of non-fiction",
    "Nightly retrospective & tomorrow plan",
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
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute("PRAGMA foreign_keys = ON")

            # 1. Tasks table
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

            # 5. Metadata table (timestamps, cursors, schema version)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
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

            conn.commit()

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

        # Backfill tasks missing UUID or updated_at
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

        # Backfill completions missing UUIDs
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
            INSERT INTO sync_outbox (table_name, record_uuid, action, payload, created_at, attempts)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (table_name, record_uuid, action, json.dumps(payload), now_iso),
        )

    # -----------------------------------------------------------------------
    # Task Operations
    # -----------------------------------------------------------------------

    def get_tasks(self) -> List[Task]:
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                SELECT id, title, sort_order, created_at, updated_at, uuid, active
                FROM tasks
                WHERE deleted = 0 AND active = 1
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
            title = "Untitled Routine"
        t_uuid = generate_uuid()
        now_iso = current_iso_time()
        with self._get_conn() as conn:
            cur = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM tasks WHERE deleted = 0")
            next_order = cur.fetchone()[0]
            cur = conn.execute(
                """
                INSERT INTO tasks (title, sort_order, uuid, created_at, updated_at, dirty, deleted, active)
                VALUES (?, ?, ?, ?, ?, 1, 0, 1)
                """,
                (title, next_order, t_uuid, now_iso, now_iso),
            )
            task_id = cur.lastrowid
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

            # Soft delete in local DB + flag dirty
            conn.execute("UPDATE tasks SET deleted = 1, updated_at = ?, dirty = 1 WHERE id = ?", (now_iso, task_id))
            conn.execute("DELETE FROM completions WHERE task_id = ?", (task_id,))

            # Normalize remaining task sort orders
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
    # Completions
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
            return {
                row["task_id"]: Completion(
                    task_id=row["task_id"],
                    date=row["date"],
                    done=bool(row["done"]),
                    uuid=row["uuid"] or generate_uuid(),
                    task_uuid=row["task_uuid"] or "",
                    completed_at=str(row["completed_at"] or ""),
                    updated_at=str(row["updated_at"] or ""),
                )
                for row in cur.fetchall()
            }

    def toggle_completion(self, task_id: int, date_str: str) -> bool:
        now_iso = current_iso_time()
        with self._get_conn() as conn:
            t_row = conn.execute("SELECT uuid FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not t_row:
                return False
            t_uuid = t_row["uuid"]

            cur = conn.execute(
                "SELECT uuid, done FROM completions WHERE task_id = ? AND date = ?",
                (task_id, date_str),
            )
            row = cur.fetchone()
            new_state = 1
            if row is not None:
                new_state = 0 if row["done"] else 1
                c_uuid = row["uuid"] or generate_uuid()
                conn.execute(
                    """
                    UPDATE completions
                    SET done = ?, updated_at = ?, completed_at = ?, dirty = 1
                    WHERE task_id = ? AND date = ?
                    """,
                    (new_state, now_iso, now_iso if new_state else "", task_id, date_str),
                )
            else:
                c_uuid = generate_uuid()
                conn.execute(
                    """
                    INSERT INTO completions (task_id, date, done, uuid, task_uuid, completed_at, updated_at, dirty)
                    VALUES (?, ?, 1, ?, ?, ?, ?, 1)
                    """,
                    (task_id, date_str, c_uuid, t_uuid, now_iso, now_iso),
                )

            self._enqueue_outbox(
                conn,
                "completions",
                c_uuid,
                "UPSERT",
                {
                    "id": c_uuid,
                    "task_id": t_uuid,
                    "date": date_str,
                    "done": bool(new_state),
                    "completed_at": now_iso if new_state else None,
                    "updated_at": now_iso,
                },
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
                SELECT c.date, SUM(c.done) as done_count
                FROM completions c
                JOIN tasks t ON c.task_id = t.id
                WHERE c.date >= ? AND c.date <= ? AND t.deleted = 0
                GROUP BY c.date
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

    # -----------------------------------------------------------------------
    # Journal Operations (Dual-Mirrored Plain Text + SQLite + Outbox)
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
                SELECT id, uuid, date, content, word_count, created_at, updated_at, deleted
                FROM journal_entries
                WHERE date = ? AND deleted = 0
                """,
                (date_str,),
            )
            row = cur.fetchone()

            if row is not None:
                # If file exists and differs or file is missing, reconcile
                db_content = row["content"]
                if file_content is not None and file_content != db_content:
                    # File on disk was modified externally!
                    w_count = len(file_content.split()) if file_content else 0
                    now_iso = current_iso_time()
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
                        row["uuid"],
                        "UPSERT",
                        {
                            "id": row["uuid"],
                            "date": date_str,
                            "content": file_content,
                            "word_count": w_count,
                            "created_at": str(row["created_at"]),
                            "updated_at": now_iso,
                        },
                    )
                    conn.commit()
                    return JournalEntry(
                        id=row["id"],
                        uuid=row["uuid"],
                        date=date_str,
                        content=file_content,
                        word_count=w_count,
                        created_at=str(row["created_at"]),
                        updated_at=now_iso,
                        mtime=file_mtime,
                    )
                elif file_content is None and db_content:
                    # Write mirror file to disk
                    try:
                        file_path.write_text(db_content, encoding="utf-8")
                        file_mtime = file_path.stat().st_mtime
                    except Exception:
                        pass

                return JournalEntry(
                    id=row["id"],
                    uuid=row["uuid"],
                    date=row["date"],
                    content=row["content"],
                    word_count=row["word_count"],
                    created_at=str(row["created_at"]),
                    updated_at=str(row["updated_at"]),
                    mtime=file_mtime,
                )

            elif file_content is not None and file_content.strip():
                # Entry exists in txt file but not in DB yet
                j_uuid = generate_uuid()
                now_iso = current_iso_time()
                w_count = len(file_content.split())
                conn.execute(
                    """
                    INSERT INTO journal_entries (uuid, date, content, word_count, created_at, updated_at, dirty, deleted)
                    VALUES (?, ?, ?, ?, ?, ?, 1, 0)
                    """,
                    (j_uuid, date_str, file_content, w_count, now_iso, now_iso),
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
                        "created_at": now_iso,
                        "updated_at": now_iso,
                    },
                )
                conn.commit()
                return JournalEntry(
                    uuid=j_uuid,
                    date=date_str,
                    content=file_content,
                    word_count=w_count,
                    created_at=now_iso,
                    updated_at=now_iso,
                    mtime=file_mtime,
                )

        return None

    def save_journal_entry(
        self,
        date_str: str,
        content: str,
        expected_mtime: Optional[float] = None,
    ) -> Tuple[JournalEntry, bool]:
        """
        Save journal entry to both plain txt file and SQLite.
        Returns (entry, is_external_collision).
        """
        file_path = self.get_journal_file_path(date_str)
        is_collision = False

        if expected_mtime is not None and file_path.exists():
            current_mtime = file_path.stat().st_mtime
            if abs(current_mtime - expected_mtime) > 0.001:
                # File on disk changed externally
                is_collision = True

        # Write clean human-readable plain text
        file_path.write_text(content, encoding="utf-8")
        new_mtime = file_path.stat().st_mtime
        w_count = len(content.split()) if content else 0
        now_iso = current_iso_time()

        with self._get_conn() as conn:
            cur = conn.execute(
                "SELECT id, uuid, created_at FROM journal_entries WHERE date = ?",
                (date_str,),
            )
            row = cur.fetchone()
            if row is not None:
                j_id = row["id"]
                j_uuid = row["uuid"]
                c_at = str(row["created_at"])
                conn.execute(
                    """
                    UPDATE journal_entries
                    SET content = ?, word_count = ?, updated_at = ?, dirty = 1, deleted = 0
                    WHERE id = ?
                    """,
                    (content, w_count, now_iso, j_id),
                )
            else:
                j_uuid = generate_uuid()
                c_at = now_iso
                cur = conn.execute(
                    """
                    INSERT INTO journal_entries (uuid, date, content, word_count, created_at, updated_at, dirty, deleted)
                    VALUES (?, ?, ?, ?, ?, ?, 1, 0)
                    """,
                    (j_uuid, date_str, content, w_count, c_at, now_iso),
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
