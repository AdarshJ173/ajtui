"""
Test Schema Migrations & Legacy DB Compatibility
================================================
Verifies that existing tables (tasks, completions, journal_entries, sync_outbox, sync_meta)
are never dropped or corrupted, and that pre-existing data survives and renders cleanly.
"""

import sqlite3
import tempfile
from pathlib import Path
import pytest

from lifeos.db.local import DatabaseManager


def test_legacy_database_migration_preserves_data():
    """Create a raw legacy DB with minimal v1 schema, populate rows, and run DatabaseManager migration."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "legacy.db"
        journal_dir = Path(tmp) / "journal"
        journal_dir.mkdir(parents=True, exist_ok=True)

        # 1. Create legacy v1 SQLite schema manually
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE completions (
                task_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (task_id, date),
                FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE journal_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                word_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        # Insert legacy rows
        conn.execute("INSERT INTO tasks (title, sort_order) VALUES ('Legacy Habit 1', 0)")
        conn.execute("INSERT INTO tasks (title, sort_order) VALUES ('Legacy Habit 2', 1)")
        conn.execute("INSERT INTO completions (task_id, date, done) VALUES (1, '2026-08-01', 1)")
        conn.execute("INSERT INTO completions (task_id, date, done) VALUES (2, '2026-08-01', 0)")
        conn.execute("INSERT INTO journal_entries (date, content, word_count) VALUES ('2026-08-01', 'Legacy journal entry.', 3)")
        conn.commit()
        conn.close()

        # 2. Boot DatabaseManager against this legacy database
        db = DatabaseManager(db_path=db_path, journal_dir=journal_dir)

        # 3. Verify all legacy data survived untouched
        tasks = db.get_tasks()
        assert len(tasks) == 2
        assert tasks[0].title == "Legacy Habit 1"
        assert tasks[1].title == "Legacy Habit 2"
        assert tasks[0].uuid != ""  # Migrated with a new uuid
        assert tasks[1].uuid != ""

        comps = db.get_day_completions("2026-08-01")
        assert comps[1].done is True
        assert comps[2].done is False

        entry = db.get_journal_entry("2026-08-01")
        assert entry is not None
        assert entry.content == "Legacy journal entry."

        # 4. Verify new v3 tables exist and function properly
        proj = db.add_project(title="Test V3 Project", area="Career", outcome="Verify V3 migrations")
        assert proj.id is not None
        act = db.add_action(title="Write v3 tests", project_id=proj.id, estimate_minutes=30)
        assert act.id is not None
        db.set_daily_priority("2026-08-01", 1, act.id)
        prios = db.get_daily_priorities("2026-08-01")
        assert len(prios) == 1
        assert prios[0].action.title == "Write v3 tests"
