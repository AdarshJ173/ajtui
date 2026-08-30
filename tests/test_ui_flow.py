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
