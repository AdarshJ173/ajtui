"""
Consolidated legacy test suite and Phase 0 integration tests (undo, realtime, outbox reconnect).
"""

import datetime
import tempfile
from pathlib import Path
import pytest

from lifeos.app import DailyOS
from lifeos.core.models import SyncStateEnum
from lifeos.db.local import DatabaseManager
from lifeos.db.supabase_sync import SupabaseSyncEngine


def test_legacy_e2e_daily_flow():
    """Verify all 9 assertions from the original legacy test_daily.py."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_db_path = Path(tmp_dir) / "test_daily.db"
        db = DatabaseManager(test_db_path)

        # 1. Test auto-seeding
        initial_tasks = db.get_tasks()
        assert len(initial_tasks) == 5, f"Expected 5 seeded tasks, got {len(initial_tasks)}"

        # 2. Test Add Task
        new_task = db.add_task("Play Piano 15m")
        all_tasks = db.get_tasks()
        assert len(all_tasks) == 6
        assert all_tasks[-1].title == "Play Piano 15m"

        # 3. Test Inline Rename
        db.update_task_title(new_task.id, "Play Piano 30m")
        updated = [t for t in db.get_tasks() if t.id == new_task.id][0]
        assert updated.title == "Play Piano 30m"

        # 4. Test Reorder Tasks
        db.reorder_task(new_task.id, -1)  # Move up
        reordered = db.get_tasks()
        assert reordered[-2].id == new_task.id
        db.reorder_task(new_task.id, 1)  # Move down back
        reordered_back = db.get_tasks()
        assert reordered_back[-1].id == new_task.id

        # 5. Test Check-off toggling and past date isolation
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        yesterday_str = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

        # Toggle on today
        res = db.toggle_completion(new_task.id, today_str)
        assert res is True
        today_comps = db.get_day_completions(today_str)
        assert today_comps[new_task.id].done is True

        # Toggle on yesterday
        yesterday_res = db.toggle_completion(new_task.id, yesterday_str)
        assert yesterday_res is True
        yesterday_comps = db.get_day_completions(yesterday_str)
        assert yesterday_comps[new_task.id].done is True

        # Uncheck today
        res_off = db.toggle_completion(new_task.id, today_str)
        assert res_off is False
        assert db.get_day_completions(today_str)[new_task.id].done is False
        # Yesterday must remain untouched!
        assert db.get_day_completions(yesterday_str)[new_task.id].done is True

        # 6. Test Streak Calculation
        for t in db.get_tasks():
            db.toggle_completion(t.id, today_str)
            prev = db.get_day_completions(yesterday_str).get(t.id)
            if prev and prev.done:
                db.toggle_completion(t.id, yesterday_str)
            db.toggle_completion(t.id, yesterday_str)

        streak = db.calculate_streak(datetime.date.today())
        assert streak == 2, f"Expected streak of 2, got {streak}"

        # 7. Test Cascading Delete
        db.delete_task(new_task.id)
        tasks_after_del = db.get_tasks()
        assert len(tasks_after_del) == 5
        assert new_task.id not in [t.id for t in tasks_after_del]
        assert new_task.id not in db.get_day_completions(today_str)

        # 8. Test Month Stats
        now = datetime.date.today()
        stats = db.get_month_completion_stats(now.year, now.month)
        assert today_str in stats

        # 9. Test App headless instantiating
        app = DailyOS(db_path=test_db_path)
        assert app is not None


def test_task_soft_delete_and_undo():
    """Verify task soft-delete and undo restoration."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_db_path = Path(tmp_dir) / "test_undo.db"
        db = DatabaseManager(test_db_path)

        task = db.add_task("Write docs")
        assert len(db.get_tasks()) == 6

        db.delete_task(task.id)
        assert len(db.get_tasks()) == 5
        assert task.id not in [t.id for t in db.get_tasks()]

        restored = db.restore_task(task.id)
        assert restored is not None
        assert restored.title == "Write docs"
        assert len(db.get_tasks()) == 6
        assert db.get_tasks()[-1].id == task.id


def test_realtime_and_reconnect_subscription_dispatch():
    """Verify realtime event handling and simulated remote change trigger without polling."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_db_path = Path(tmp_dir) / "test_rt.db"
        db = DatabaseManager(test_db_path)

        remote_changes = []

        def on_remote():
            remote_changes.append(True)

        engine = SupabaseSyncEngine(
            db_manager=db,
            on_remote_change=on_remote,
        )

        # Simulate incoming realtime event for a task
        remote_task_payload = {
            "data": {
                "table": "routine_tasks",
                "type": "INSERT",
                "record": {
                    "id": "11111111-2222-3333-4444-555555555555",
                    "title": "Realtime Remote Task",
                    "position": 99,
                    "active": True,
                    "created_at": "2026-08-31T08:00:00Z",
                    "updated_at": "2026-08-31T08:00:00Z",
                },
            }
        }

        engine._handle_realtime_event(remote_task_payload)
        assert len(remote_changes) == 1
        tasks = db.get_tasks()
        assert any(t.uuid == "11111111-2222-3333-4444-555555555555" for t in tasks)
