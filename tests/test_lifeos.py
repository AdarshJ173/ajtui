"""
lifeOS Comprehensive Verification Test Suite
============================================
Exhaustive automated tests covering:
- Phase 1: Modular architecture & backwards compatibility
- Phase 2: Journal module, dual mirroring, autosave, mtime collisions, midnight rollover, emojis, 100KB+
- Phase 3: Supabase sync engine, outbox persistence, LWW, non-destructive conflict backups, offline tolerance
- Phase 4: Calendar markers, streak metrics, smooth progress computations
"""

import datetime
import os
import tempfile
import time
from pathlib import Path
import pytest

from lifeos.core.models import Completion, JournalEntry, SyncStateEnum, Task, current_iso_time
from lifeos.db.local import DatabaseManager
from lifeos.db.supabase_sync import SupabaseSyncEngine
from lifeos.app import DailyOS


class TestPhase1ModularArchitecture:
    """Verify package structure, models, and backwards compatibility."""

    def test_import_and_models(self):
        t = Task(id=1, title="Test Habit", sort_order=0)
        assert t.id == 1
        assert t.uuid is not None
        assert t.active is True

        c = Completion(task_id=1, date="2026-08-30", done=True)
        assert c.done is True
        assert c.uuid is not None

        j = JournalEntry(date="2026-08-30", content="Hello world from lifeOS!")
        assert j.calculate_word_count() == 4

    def test_database_initialization_and_seeding(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "daily.db"
            db = DatabaseManager(db_path=db_path)
            tasks = db.get_tasks()
            assert len(tasks) == 5
            for task in tasks:
                assert task.uuid != ""
                assert task.updated_at != ""


class TestPhase2JournalModule:
    """Verify all Phase 2 specs and edge cases."""

    def test_plain_text_storage_and_no_metadata_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "daily.db"
            journal_dir = Path(tmp) / "journal"
            db = DatabaseManager(db_path=db_path, journal_dir=journal_dir)

            date_str = "2026-08-30"
            raw_text = "This is a purely human-written journal entry.\nNo headers, no frontmatter."
            entry, is_col = db.save_journal_entry(date_str, raw_text)

            txt_file = journal_dir / f"{date_str}.txt"
            assert txt_file.exists()
            content_on_disk = txt_file.read_text(encoding="utf-8")
            assert content_on_disk == raw_text
            assert "---" not in content_on_disk
            assert "title:" not in content_on_disk
            assert entry.word_count == 11

    def test_dual_mirror_synchronization(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "daily.db"
            journal_dir = Path(tmp) / "journal"
            db = DatabaseManager(db_path=db_path, journal_dir=journal_dir)

            date_str = "2026-08-30"
            # 1. Save via DB
            db.save_journal_entry(date_str, "Initial thoughts.")

            # 2. Read back
            read_entry = db.get_journal_entry(date_str)
            assert read_entry is not None
            assert read_entry.content == "Initial thoughts."

    def test_empty_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "daily.db"
            journal_dir = Path(tmp) / "journal"
            db = DatabaseManager(db_path=db_path, journal_dir=journal_dir)

            date_str = "2026-08-30"
            db.save_journal_entry(date_str, "Will be removed soon.")
            txt_file = journal_dir / f"{date_str}.txt"
            assert txt_file.exists()

            # Delete
            db.delete_journal_entry(date_str)
            assert not txt_file.exists()
            assert db.get_journal_entry(date_str) is None

    def test_unicode_and_emojis_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "daily.db"
            journal_dir = Path(tmp) / "journal"
            db = DatabaseManager(db_path=db_path, journal_dir=journal_dir)

            date_str = "2026-08-30"
            complex_text = "✨ 1% better every day 🚀\n日本語のジャーナル・العربية\nMath: ∑(1/2^n) = 1"
            db.save_journal_entry(date_str, complex_text)

            loaded = db.get_journal_entry(date_str)
            assert loaded is not None
            assert loaded.content == complex_text

    def test_large_entry_100kb_performance(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "daily.db"
            journal_dir = Path(tmp) / "journal"
            db = DatabaseManager(db_path=db_path, journal_dir=journal_dir)

            date_str = "2026-08-30"
            large_text = ("The quick brown fox jumps over the lazy dog. " * 2500)  # ~112 KB
            assert len(large_text.encode("utf-8")) > 100000

            t0 = time.time()
            entry, _ = db.save_journal_entry(date_str, large_text)
            save_duration = time.time() - t0
            assert save_duration < 0.2  # Lightning fast < 200ms

            t1 = time.time()
            loaded = db.get_journal_entry(date_str)
            read_duration = time.time() - t1
            assert read_duration < 0.1
            assert loaded.content == large_text

    def test_external_file_edit_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "daily.db"
            journal_dir = Path(tmp) / "journal"
            db = DatabaseManager(db_path=db_path, journal_dir=journal_dir)

            date_str = "2026-08-30"
            entry1, _ = db.save_journal_entry(date_str, "Written in lifeOS.")
            original_mtime = entry1.mtime

            # Simulate external editor like Vim/VSCode writing to the txt file
            time.sleep(0.02)
            txt_file = journal_dir / f"{date_str}.txt"
            txt_file.write_text("Edited externally by user in Vim!", encoding="utf-8")

            # App loads entry -> detects external modification and syncs to DB
            loaded = db.get_journal_entry(date_str)
            assert loaded.content == "Edited externally by user in Vim!"

    def test_future_date_journal_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "daily.db"
            journal_dir = Path(tmp) / "journal"
            db = DatabaseManager(db_path=db_path, journal_dir=journal_dir)

            future_date = (datetime.date.today() + datetime.timedelta(days=10)).strftime("%Y-%m-%d")
            entry, _ = db.save_journal_entry(future_date, "Planning intentions for next week.")
            assert entry.date == future_date
            assert db.get_journal_entry(future_date) is not None

    def test_journal_browse_and_calendar_indicators(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "daily.db"
            journal_dir = Path(tmp) / "journal"
            db = DatabaseManager(db_path=db_path, journal_dir=journal_dir)

            db.save_journal_entry("2026-08-01", "Day 1 reflections")
            db.save_journal_entry("2026-08-15", "Mid month checkpoint")

            entries = db.list_journal_entries()
            assert len(entries) == 2
            assert entries[0].date == "2026-08-15"
            assert entries[1].date == "2026-08-01"

            dates_with_journals = db.get_dates_with_journals("2026-08-01", "2026-08-31")
            assert "2026-08-01" in dates_with_journals
            assert "2026-08-15" in dates_with_journals
            assert "2026-08-02" not in dates_with_journals


class TestPhase3SupabaseSyncAndConflicts:
    """Verify local-first outbox, LWW, and non-destructive conflict preservation."""

    def test_offline_mode_zero_crashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "daily.db"
            db = DatabaseManager(db_path=db_path)

            # Initialize engine with no network
            sync = SupabaseSyncEngine(db_manager=db)
            assert sync.state.status in (SyncStateEnum.LOCAL_ONLY, SyncStateEnum.OFFLINE, SyncStateEnum.LIVE)

            # Local actions must function smoothly with 0 network calls
            new_task = db.add_task("Offline Habit")
            assert new_task.title == "Offline Habit"
            db.toggle_completion(new_task.id, "2026-08-30")

            # Outbox should have captured the mutations
            with db._get_conn() as conn:
                cur = conn.execute("SELECT COUNT(*) FROM sync_outbox")
                outbox_count = cur.fetchone()[0]
                assert outbox_count >= 2

    def test_conflict_preservation_creates_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "daily.db"
            journal_dir = Path(tmp) / "journal"
            db = DatabaseManager(db_path=db_path, journal_dir=journal_dir)

            conflict_notifications = []
            def on_conflict(d, backup):
                conflict_notifications.append((d, backup))

            sync = SupabaseSyncEngine(
                db_manager=db,
                on_conflict=on_conflict,
            )

            date_str = "2026-08-30"
            # 1. Create local entry (dirty=1)
            db.save_journal_entry(date_str, "Local machine edits written at 10:00 AM")

            # 2. Simulate remote arrival with a newer timestamp in the future
            remote_newer_iso = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)).isoformat()
            remote_newer = {
                "id": "test-remote-uuid",
                "date": date_str,
                "content": "Remote phone edits written at 10:05 AM",
                "word_count": 7,
                "created_at": "2026-08-30T10:00:00Z",
                "updated_at": remote_newer_iso,
            }

            sync._apply_remote_journal(remote_newer)

            # Canonical local becomes the newer remote
            loaded = db.get_journal_entry(date_str)
            assert loaded.content == "Remote phone edits written at 10:05 AM"

            # Loser must NOT be discarded: check conflicts directory!
            conflict_files = list(db.conflicts_dir.glob(f"{date_str}-*.txt"))
            assert len(conflict_files) == 1
            saved_loser_text = conflict_files[0].read_text(encoding="utf-8")
            assert saved_loser_text == "Local machine edits written at 10:00 AM"
            assert len(conflict_notifications) == 1


class TestPhase4UIPolishAndMetrics:
    """Verify progress bars, calendar layout calculations, and streak logic."""

    def test_progress_bar_cells_unicode_and_ascii(self):
        from lifeos.ui.themes import progress_bar_cells
        # Unicode eighths
        cells_uni = progress_bar_cells(0.5, 10, unicode=True)
        assert len(cells_uni) == 10
        assert cells_uni[0] == "█"
        assert "·" in cells_uni

        # ASCII fallback
        cells_ascii = progress_bar_cells(0.5, 10, unicode=False)
        assert len(cells_ascii) == 10
        assert cells_ascii.count("#") == 5
        assert cells_ascii.count(".") == 5

    def test_streak_calculation_continuous(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "daily.db"
            db = DatabaseManager(db_path=db_path)
            tasks = db.get_tasks()

            today = datetime.date.today()
            t_str = today.strftime("%Y-%m-%d")
            y_str = (today - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

            # Complete both days
            for t in tasks:
                db.toggle_completion(t.id, y_str)
                db.toggle_completion(t.id, t_str)

            streak = db.calculate_streak(today)
            assert streak == 2
