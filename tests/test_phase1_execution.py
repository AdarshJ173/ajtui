"""
Phase 1 Execution OS Invariants and Operations Tests
====================================================
Verifies:
- Action physical title validation & rejection of vague actions
- Daily priorities constraints (max 3 ranks per date, estimate > 0)
- Projects CRUD and active project next action invariant
- Capacity budgeting and Now card resolution
- Quick capture to inbox / action / project conversion
- Daily close flow journal append formatting (no markdown clutter)
"""

import datetime
import tempfile
from pathlib import Path
import pytest

from lifeos.core.models import (
    ActionStatus,
    BlockKind,
    BlockStatus,
    ProjectStatus,
    is_valid_physical_action,
)
from lifeos.db.local import DatabaseManager


def test_action_title_validation():
    """Verify physical action validation rejects vague actions and accepts startable steps."""
    valid, hint = is_valid_physical_action("do project")
    assert not valid
    assert "vague" in hint.lower() or "physical" in hint.lower()

    valid, hint = is_valid_physical_action("work")
    assert not valid

    valid, hint = is_valid_physical_action("")
    assert not valid

    valid, hint = is_valid_physical_action("Define SQLite schema for projects in local.py")
    assert valid
    assert hint == ""


def test_project_and_action_invariants():
    """Verify project creation requires/ensures a concrete next action."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = DatabaseManager(Path(tmp_dir) / "test.db")

        # Adding project with valid physical initial action
        proj = db.add_project(
            title="Dyzeee Release",
            area="Career",
            outcome="Publish v0.1 release artifact",
            initial_action_title="Implement OAuth redirect handler in auth.py",
            initial_action_estimate=45,
        )
        assert proj.id is not None
        assert proj.title == "Dyzeee Release"
        assert len(proj.actions) == 1
        assert proj.actions[0].title == "Implement OAuth redirect handler in auth.py"
        assert proj.actions[0].estimate_minutes == 45
        assert proj.actions[0].status == ActionStatus.NEXT

        # Vague action creation should raise ValueError
        with pytest.raises(ValueError) as exc:
            db.add_action(title="do project", project_id=proj.id)
        assert "vague" in str(exc.value).lower() or "physical" in str(exc.value).lower()


def test_daily_priorities_constraints():
    """Verify max 3 priorities per date and estimate_minutes > 0 constraint."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = DatabaseManager(Path(tmp_dir) / "test.db")
        today_str = datetime.date.today().strftime("%Y-%m-%d")

        # Create 4 concrete actions
        a1 = db.add_action("Draft SQLite migration in local.py", estimate_minutes=30)
        a2 = db.add_action("Build Today Command Center UI", estimate_minutes=90)
        a3 = db.add_action("Run pytest verification suite", estimate_minutes=20)
        a4 = db.add_action("Write release notes in README.md", estimate_minutes=15)

        # Set ranks 1, 2, 3
        p1 = db.set_daily_priority(today_str, 1, a1.id)
        p2 = db.set_daily_priority(today_str, 2, a2.id)
        p3 = db.set_daily_priority(today_str, 3, a3.id)

        assert p1.rank == 1
        assert p2.rank == 2
        assert p3.rank == 3

        # Rank 4 must be rejected
        with pytest.raises(ValueError):
            db.set_daily_priority(today_str, 4, a4.id)

        # Action with 0 estimate cannot be committed
        a_zero = db.add_action("Check build logs", estimate_minutes=30)
        # Update to 0 minutes
        with db._get_conn() as conn:
            conn.execute("UPDATE actions SET estimate_minutes = 0 WHERE id = ?", (a_zero.id,))
            conn.commit()

        with pytest.raises(ValueError) as exc_zero:
            db.set_daily_priority(today_str, 1, a_zero.id)
        assert "estimate_minutes" in str(exc_zero.value)


def test_capacity_budget_and_now_card():
    """Verify capacity budget calculation and single Now card logic."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = DatabaseManager(Path(tmp_dir) / "test.db")
        today_str = datetime.date.today().strftime("%Y-%m-%d")

        # Default budget
        budget = db.get_day_capacity_budget(today_str, capacity_minutes=210)
        assert budget["capacity_minutes"] == 210
        assert "planned_minutes" in budget
        assert "available_minutes" in budget

        # Now card returns either active block, top priority, or top unblocked action
        now_card = db.get_now_card(today_str, "10:00")
        assert now_card is not None
        assert "title" in now_card
        assert "minutes" in now_card


def test_quick_capture_and_triage():
    """Verify global capture and triage into actions and projects."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = DatabaseManager(Path(tmp_dir) / "test.db")

        # Capture item
        item = db.add_inbox_item("Investigate OpenRouter fallback rate limits")
        assert item.status.value == "unprocessed"
        assert len(db.get_inbox_items()) >= 1

        # Convert to action
        act = db.convert_inbox_to_action(
            inbox_id=item.id,
            title="Benchmark OpenRouter models with test script",
            estimate_minutes=25,
        )
        assert act.id is not None
        assert act.title == "Benchmark OpenRouter models with test script"

        # Inbox item should now be converted
        unprocessed = db.get_inbox_items()
        assert not any(i.id == item.id for i in unprocessed)


def test_daily_close_journal_append_format():
    """Verify daily close summary appends cleanly without markdown syntax clutter."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = DatabaseManager(Path(tmp_dir) / "test.db")
        today_str = datetime.date.today().strftime("%Y-%m-%d")

        # Initial journal entry
        db.save_journal_entry(today_str, "Morning focus went well.")

        close_text = (
            "\n\n--- DAILY CLOSE ---\n"
            "EXECUTION:\n"
            "  Planned deep work: 3h 30m | Actual: 2h 10m\n"
            "  Priorities completed: 2/3\n"
            "  Routines completed: 4/5\n\n"
            "1. What moved forward?\n"
            "   Shipped Phase 1 execution schema and commands.\n\n"
            "2. What blocked me?\n"
            "   None\n\n"
            "3. What is tomorrow's first action?\n"
            "   Implement Plan timeline screen\n"
        )

        existing = db.get_journal_entry(today_str)
        assert existing is not None
        updated_content = existing.content + close_text
        db.save_journal_entry(today_str, updated_content)

        read_entry = db.get_journal_entry(today_str)
        assert read_entry is not None
        assert "--- DAILY CLOSE ---" in read_entry.content
        assert "Shipped Phase 1" in read_entry.content
        assert "# " not in read_entry.content  # No markdown header syntax
        assert "**" not in read_entry.content  # No markdown bold syntax
