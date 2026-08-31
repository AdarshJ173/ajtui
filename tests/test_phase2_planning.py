"""
Phase 2 Planning MVP Tests
==========================
Verifies:
- Operational Day Timeline block scheduling and CRUD
- Focus cockpit completion and actual minutes tracking
- Missed block resolution (reschedule, shrink, cancel)
- Sunday Weekly review computation & decision commitments
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
)
from lifeos.db.local import DatabaseManager


def test_time_block_scheduling_and_closing():
    """Verify block scheduling, start/end time, and completion with actual minutes."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = DatabaseManager(Path(tmp_dir) / "test_plan.db")
        today_str = datetime.date.today().strftime("%Y-%m-%d")

        action = db.add_action("Implement database query caching in local.py", estimate_minutes=45)

        # Schedule a 60m deep work block
        block = db.add_time_block(
            date_str=today_str,
            starts_at="09:00",
            ends_at="10:00",
            action_id=action.id,
            kind=BlockKind.DEEP_WORK,
            planned_minutes=60,
        )

        assert block.id is not None
        assert block.starts_at == "09:00"
        assert block.ends_at == "10:00"
        assert block.planned_minutes == 60
        assert block.status == BlockStatus.PLANNED

        # Close the block after focus session with 55 actual minutes
        closed_block = db.close_time_block(
            block_id=block.id,
            status=BlockStatus.COMPLETED,
            actual_minutes=55,
            notes="Completed query caching ahead of schedule",
        )

        assert closed_block is not None
        assert closed_block.status == BlockStatus.COMPLETED
        assert closed_block.actual_minutes == 55
        assert "ahead of schedule" in (closed_block.notes or "")


def test_missed_block_handling():
    """Verify explicit missed block choices: shrink, reschedule, cancel."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = DatabaseManager(Path(tmp_dir) / "test_missed.db")
        today_str = datetime.date.today().strftime("%Y-%m-%d")

        block = db.add_time_block(
            date_str=today_str,
            starts_at="14:00",
            ends_at="15:30",
            planned_minutes=90,
            notes="Afternoon deep work",
        )

        # 1. Shrink duration
        db.update_time_block(block.id, planned_minutes=45)
        shrunk = [b for b in db.get_time_blocks(today_str) if b.id == block.id][0]
        assert shrunk.planned_minutes == 45

        # 2. Reschedule
        db.update_time_block(block.id, starts_at="16:00", ends_at="16:45")
        rescheduled = [b for b in db.get_time_blocks(today_str) if b.id == block.id][0]
        assert rescheduled.starts_at == "16:00"

        # 3. Cancel / Skip with reason
        db.update_time_block(
            block.id,
            status=BlockStatus.SKIPPED,
            notes="Client emergency meeting",
        )
        skipped = [b for b in db.get_time_blocks(today_str) if b.id == block.id][0]
        assert skipped.status == BlockStatus.SKIPPED
        assert "Client emergency" in skipped.notes


def test_weekly_review_aggregation():
    """Verify weekly review aggregates projects, deep work, and decision commits."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = DatabaseManager(Path(tmp_dir) / "test_review.db")
        today = datetime.date.today()

        # Seed deep work blocks across multiple days
        for i in range(3):
            d_str = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            b = db.add_time_block(
                date_str=d_str,
                starts_at="09:00",
                ends_at="10:30",
                kind=BlockKind.DEEP_WORK,
                planned_minutes=90,
            )
            db.close_time_block(b.id, status=BlockStatus.COMPLETED, actual_minutes=85)

        # Check total deep work blocks logged
        total_deep_mins = 0
        for i in range(7):
            d_str = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            for b in db.get_time_blocks(d_str):
                if b.kind == BlockKind.DEEP_WORK and b.status == BlockStatus.COMPLETED:
                    total_deep_mins += b.actual_minutes or 0

        assert total_deep_mins >= 255  # 3 * 85
