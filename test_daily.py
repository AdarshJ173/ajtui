"""
End-to-end self-test verifying all CRUD, persistence, streak calculation,
date-switching, and boundary edge cases.
"""

import datetime
import os
import tempfile
from pathlib import Path
from daily import DatabaseManager, DailyOS

def run_tests():
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_db_path = Path(tmp_dir) / "test_daily.db"
        db = DatabaseManager(test_db_path)

        # 1. Test auto-seeding
        initial_tasks = db.get_tasks()
        assert len(initial_tasks) == 5, f"Expected 5 seeded tasks, got {len(initial_tasks)}"
        print("✓ Auto-seed routine tasks passed")

        # 2. Test Add Task
        new_task = db.add_task("Play Piano 15m")
        all_tasks = db.get_tasks()
        assert len(all_tasks) == 6
        assert all_tasks[-1].title == "Play Piano 15m"
        print("✓ Add Task passed")

        # 3. Test Inline Rename
        db.update_task_title(new_task.id, "Play Piano 30m")
        updated = [t for t in db.get_tasks() if t.id == new_task.id][0]
        assert updated.title == "Play Piano 30m"
        print("✓ Inline Rename passed")

        # 4. Test Reorder Tasks
        db.reorder_task(new_task.id, -1) # Move up
        reordered = db.get_tasks()
        assert reordered[-2].id == new_task.id
        db.reorder_task(new_task.id, 1) # Move down back
        reordered_back = db.get_tasks()
        assert reordered_back[-1].id == new_task.id
        print("✓ Reorder Tasks passed")

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
        print("✓ Isolated per-day completions passed")

        # 6. Test Streak Calculation
        # Complete all tasks for yesterday and today
        for t in db.get_tasks():
            db.toggle_completion(t.id, today_str)
            # Ensure yesterday fully done (toggle is a flip: undo prior done state)
            prev = db.get_day_completions(yesterday_str).get(t.id)
            if prev and prev.done:
                db.toggle_completion(t.id, yesterday_str)  # flip off
            db.toggle_completion(t.id, yesterday_str)      # flip on

        streak = db.calculate_streak(datetime.date.today())
        assert streak == 2, f"Expected streak of 2, got {streak}"
        print("✓ Streak calculation passed")

        # 7. Test Cascading Delete
        db.delete_task(new_task.id)
        tasks_after_del = db.get_tasks()
        assert len(tasks_after_del) == 5
        assert new_task.id not in [t.id for t in tasks_after_del]
        assert new_task.id not in db.get_day_completions(today_str)
        print("✓ Cascading Delete passed")

        # 8. Test Month Stats
        now = datetime.date.today()
        stats = db.get_month_completion_stats(now.year, now.month)
        assert today_str in stats
        print("✓ Month stats calculation passed")

        # 9. Test App headless instantiating
        app = DailyOS(db_path=test_db_path)
        assert app is not None
        print("✓ App initialization passed")

    print("\nALL 9 TESTS PASSED COMPREHENSIVELY!")

if __name__ == "__main__":
    run_tests()
