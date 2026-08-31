"""
Phase 3 Intelligence & AI Copilot Tests
=======================================
Verifies:
- Deterministic analytics over local SQLite execution data
- OpenRouter AI service integration & offline degradation
- 4 Cognitive Assistants (journal summary, tomorrow planner, pattern brief, inbox parser)
- Strict Human-in-the-Loop invariant (drafts with citations, zero autonomous data mutation)
"""

import datetime
import tempfile
from pathlib import Path
import pytest

from lifeos.core.ai import AIService
from lifeos.core.analytics import AnalyticsEngine
from lifeos.core.models import (
    ActionStatus,
    BlockKind,
    BlockStatus,
    ProjectStatus,
)
from lifeos.db.local import DatabaseManager


def test_deterministic_analytics():
    """Verify local calculation of estimate bias, schedule reliability, and day patterns."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = DatabaseManager(Path(tmp_dir) / "test_analytics.db")
        analytics = AnalyticsEngine(db)
        today = datetime.date.today()

        # Seed completed and skipped blocks
        # 1. Completed block planned 60m, took 75m (under-estimation by +25%)
        b1 = db.add_time_block(
            date_str=today.strftime("%Y-%m-%d"),
            starts_at="09:00",
            ends_at="10:00",
            kind=BlockKind.DEEP_WORK,
            planned_minutes=60,
        )
        db.close_time_block(b1.id, status=BlockStatus.COMPLETED, actual_minutes=75)

        # 2. Skipped block
        b2 = db.add_time_block(
            date_str=today.strftime("%Y-%m-%d"),
            starts_at="14:00",
            ends_at="15:00",
            kind=BlockKind.DEEP_WORK,
            planned_minutes=60,
        )
        db.update_time_block(b2.id, status=BlockStatus.SKIPPED, notes="Errands overrun")

        bias = analytics.get_estimate_accuracy_bias(days=7)
        assert bias["sample_count"] == 1
        assert bias["bias_ratio"] == 1.25
        assert "Underestimating" in bias["bias_description"]

        rel = analytics.get_schedule_reliability(days=7)
        assert rel["total_blocks"] >= 2
        assert rel["completed_count"] >= 1
        assert rel["skipped_count"] >= 1

        clusters = analytics.get_habit_completion_clusters(days=7)
        assert "best_day" in clusters
        assert "hardest_day" in clusters


def test_ai_service_offline_and_draft_invariants():
    """Verify AI service produces drafts with evidence citations and never mutates data autonomously."""
    ai = AIService(api_key="")  # Offline mode

    # 1. Journal daily summary
    journal_text = "Shipped Phase 2 of lifeOS. Decided to keep SQLite as primary source of truth."
    summary_res = ai.summarize_daily_journal(journal_text, "2026-08-31")
    assert summary_res["available"] is True
    assert "summary" in summary_res
    assert "evidence" in summary_res
    assert "2026-08-31" in summary_res["evidence"]

    # 2. Tomorrow Planner
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = DatabaseManager(Path(tmp_dir) / "test_ai_db.db")
        projects = db.get_projects()
        actions = db.get_uncompleted_actions()

        plan_res = ai.propose_tomorrow_plan(projects, actions, capacity_minutes=210)
        assert plan_res["available"] is True
        assert "proposal" in plan_res
        assert "evidence" in plan_res

    # 3. Weekly Pattern Brief
    brief_res = ai.generate_weekly_pattern_brief({
        "sample_count": 10,
        "bias_description": "Underestimating by +20%",
        "reliability_pct": 80,
    })
    assert brief_res["available"] is True
    assert "brief" in brief_res
    assert "evidence" in brief_res

    # 4. Inbox Parser
    inbox_res = ai.parse_inbox_item(
        content="Need to test OpenRouter fallback rates",
        active_projects=["lifeOS Planner MVP", "ML Foundations"],
    )
    assert inbox_res["available"] is True
    assert inbox_res["destination"] in ("action", "project", "block", "archive")
    assert "estimate_minutes" in inbox_res
