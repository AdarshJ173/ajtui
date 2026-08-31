"""
lifeOS UI End-to-End Flow Tests using Textual Testing Harness
"""

import datetime
import os
import tempfile
from pathlib import Path
import pytest

from lifeos.app import DailyOS
from lifeos.ui.journal_screen import JournalScreen


@pytest.mark.anyio
async def test_boot_overlay_dismiss_on_key():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "daily.db"
        journal_dir = Path(tmp) / "journal"

        app = DailyOS(db_path=db_path, journal_dir=journal_dir)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            # Press any key to dismiss boot overlay
            await pilot.press("space")
            await pilot.pause()
            assert app.booting is False
            assert len(app.screen.query("#boot_layer")) == 0


@pytest.mark.anyio
async def test_app_screen_flow_and_journal_navigation():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "daily.db"
        journal_dir = Path(tmp) / "journal"

        app = DailyOS(db_path=db_path, journal_dir=journal_dir)
        async with app.run_test(size=(100, 30)) as pilot:
            # 1. Dismiss boot
            await pilot.press("space")
            await pilot.pause()

            # 2. Check app startup state
            assert app.current_date == datetime.date.today()
            assert len(app.tasks) == 5

            # 3. Test Task Toggle
            await pilot.press("enter")
            await pilot.pause()
            today_str = datetime.date.today().strftime("%Y-%m-%d")
            comps = app.db.get_day_completions(today_str)
            assert comps[app.tasks[0].id].done is True

            # 4. Test Open Journal (J key)
            await pilot.press("j")
            await pilot.pause()
            assert isinstance(app.screen, JournalScreen)
            assert app.screen.mode == "read"

            # 5. Enter Edit mode (Enter / E key)
            await pilot.press("enter")
            await pilot.pause()
            assert app.screen.mode == "edit"

            # 6. Save and return to read mode (Esc)
            await pilot.press("escape")
            await pilot.pause()
            assert app.screen.mode == "read"

            # 7. Return to Tasks Screen (Esc)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, JournalScreen)


@pytest.mark.anyio
async def test_journal_arrow_keys_do_not_switch_dates():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "daily.db"
        journal_dir = Path(tmp) / "journal"

        # Pre-populate past journal
        db = DailyOS(db_path=db_path, journal_dir=journal_dir).db
        past_date_str = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        db.save_journal_entry(past_date_str, "Yesterday reflection entry.")

        app = DailyOS(db_path=db_path, journal_dir=journal_dir)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("space")
            await pilot.pause()

            init_date = app.current_date

            # Open Journal
            await pilot.press("j")
            await pilot.pause()
            assert isinstance(app.screen, JournalScreen)

            # Press left / right arrow keys in journal screen -> date MUST NOT CHANGE
            await pilot.press("left")
            await pilot.pause()
            assert app.current_date == init_date

            await pilot.press("right")
            await pilot.pause()
            assert app.current_date == init_date

            # Open Browse View via B key
            await pilot.press("b")
            await pilot.pause()
            assert app.screen.mode == "browse"

            # Select past entry and hit Enter
            await pilot.press("enter")
            await pilot.pause()
            assert app.screen.mode == "read"
            assert app.screen.current_content == "Yesterday reflection entry."


@pytest.mark.anyio
async def test_execution_os_screens_and_modals():
    """Verify that all v3 execution screens and modals open and render without error."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "daily.db"
        journal_dir = Path(tmp) / "journal"

        app = DailyOS(db_path=db_path, journal_dir=journal_dir)
        proj = app.db.add_project(title="Test System", area="Career")
        app.db.add_action("Focus on next step", project_id=proj.id, estimate_minutes=30)

        async with app.run_test(size=(100, 30)) as pilot:
            # Dismiss boot
            await pilot.press("space")
            await pilot.pause()

            # 1. Open Projects Screen ('p')
            await pilot.press("p")
            await pilot.pause()
            from lifeos.ui.project_screen import ProjectScreen
            assert isinstance(app.screen, ProjectScreen)
            await pilot.press("escape")
            await pilot.pause()

            # 2. Open Plan Screen ('l')
            await pilot.press("l")
            await pilot.pause()
            from lifeos.ui.plan_screen import PlanScreen
            assert isinstance(app.screen, PlanScreen)
            await pilot.press("escape")
            await pilot.pause()

            # 3. Open Review Screen ('w')
            await pilot.press("w")
            await pilot.pause()
            from lifeos.ui.review_screen import ReviewScreen
            assert isinstance(app.screen, ReviewScreen)
            await pilot.press("escape")
            await pilot.pause()

            # 4. Open Capture Modal ('i')
            await pilot.press("i")
            await pilot.pause()
            from lifeos.ui.capture_modal import CaptureModal
            assert isinstance(app.screen, CaptureModal)
            await pilot.press("escape")
            await pilot.pause()

            # 5. Open Daily Close Modal ('x')
            await pilot.press("x")
            await pilot.pause()
            from lifeos.ui.close_modal import DailyCloseModal
            assert isinstance(app.screen, DailyCloseModal)
            await pilot.press("escape")
            await pilot.pause()

            # 6. Open Command Palette (':')
            await pilot.press("colon")
            await pilot.pause()
            from lifeos.ui.command_palette import CommandPaletteModal
            assert isinstance(app.screen, CommandPaletteModal)
            await pilot.press("escape")
            await pilot.pause()

            # 7. Open Help Modal ('?')
            await pilot.press("question_mark")
            await pilot.pause()
            from lifeos.ui.help_modal import HelpModal
            assert isinstance(app.screen, HelpModal)
            await pilot.press("escape")
            await pilot.pause()

            # 8. Start Focus Cockpit ('f')
            await pilot.press("f")
            await pilot.pause()
            from lifeos.ui.focus_cockpit import FocusCockpitModal
            assert isinstance(app.screen, FocusCockpitModal)
            await pilot.press("escape")
            await pilot.pause()


@pytest.mark.anyio
async def test_project_screen_add_action_does_not_add_dashboard_task():
    """Verify pressing 'A' in ProjectScreen adds an action to the project, NOT a task to the main dashboard."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "daily.db"
        journal_dir = Path(tmp) / "journal"

        app = DailyOS(db_path=db_path, journal_dir=journal_dir)
        proj = app.db.add_project(title="aajtui", area="Career")
        init_action_count = len(proj.actions)

        async with app.run_test(size=(100, 30)) as pilot:
            # Dismiss boot
            await pilot.press("space")
            await pilot.pause()

            init_task_count = len(app.tasks)

            # Open Projects Screen ('p')
            await pilot.press("p")
            await pilot.pause()
            from lifeos.ui.project_screen import ProjectScreen
            assert isinstance(app.screen, ProjectScreen)

            # Press 'a' inside ProjectScreen to add action
            await pilot.press("a")
            await pilot.pause()
            from lifeos.ui.widgets import TextInputModal
            assert isinstance(app.screen, TextInputModal)

            # Type action title and submit
            inp = app.screen.query_one("Input")
            inp.value = "Implement WebSocket live sync 45m"
            await pilot.press("enter")
            await pilot.pause()

            # Verify action was added to project
            refreshed_p = app.db.get_project(proj.id)
            assert len(refreshed_p.actions) == init_action_count + 1
            added_act = next(a for a in refreshed_p.actions if a.title == "Implement WebSocket live sync")
            assert added_act.estimate_minutes == 45

            # Exit ProjectScreen to main dashboard
            await pilot.press("escape")
            await pilot.pause()

            # Main dashboard tasks MUST NOT have changed
            assert len(app.tasks) == init_task_count


@pytest.mark.anyio
async def test_auto_close_day_functionality():
    """Verify auto_close_day banks the day and appends AI close summary to journal."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "daily.db"
        journal_dir = Path(tmp) / "journal"

        app = DailyOS(db_path=db_path, journal_dir=journal_dir)
        yesterday_str = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

        # Add project and priority for yesterday
        proj = app.db.add_project("Autonomous Engine")
        act = app.db.add_action("Refactor state machine", project_id=proj.id)
        app.db.set_daily_priority(yesterday_str, 1, act.id)

        # Trigger auto close
        app.auto_close_day(yesterday_str)

        # Verify journal entry was created and formatted
        entry = app.db.get_journal_entry(yesterday_str)
        assert entry is not None
        assert "--- DAILY CLOSE ---" in entry.content
        assert "EXECUTION:" in entry.content
        assert "1. What moved forward?" in entry.content
        assert "3. What is tomorrow's first action?" in entry.content


