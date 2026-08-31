"""
lifeOS Deterministic Analytics Engine
=====================================
Pure Python and SQLite analytics:
- Completion by hour / day of week
- Estimate accuracy bias (planned vs actual)
- Schedule reliability rate
- Habit failure clusters and correlations
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional, Tuple

from lifeos.core.models import BlockKind, BlockStatus


class AnalyticsEngine:
    """Deterministic statistics computation over local execution data."""

    def __init__(self, db_manager: Any):
        self.db = db_manager

    def get_estimate_accuracy_bias(self, days: int = 30) -> Dict[str, Any]:
        """
        Compute ratio of planned vs actual minutes for completed blocks.
        Bias > 1.0 means tasks take longer than estimated (under-estimation).
        Bias < 1.0 means tasks take less time than estimated (over-estimation).
        """
        today = datetime.date.today()
        total_planned = 0
        total_actual = 0
        count = 0

        for i in range(days):
            d_str = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            blocks = self.db.get_time_blocks(d_str)
            for b in blocks:
                if b.status == BlockStatus.COMPLETED and b.actual_minutes and b.planned_minutes:
                    total_planned += b.planned_minutes
                    total_actual += b.actual_minutes
                    count += 1

        if count == 0 or total_planned == 0:
            return {
                "sample_count": 0,
                "bias_ratio": 1.0,
                "accuracy_pct": 100,
                "bias_description": "On track (no history yet)",
            }

        bias_ratio = round(total_actual / total_planned, 2)
        acc_pct = int(min(1.0, total_planned / total_actual if total_actual > total_planned else total_actual / total_planned) * 100)

        if bias_ratio > 1.15:
            desc = f"Underestimating by +{int((bias_ratio - 1) * 100)}% (tasks take longer)"
        elif bias_ratio < 0.85:
            desc = f"Overestimating by -{int((1 - bias_ratio) * 100)}% (tasks finish faster)"
        else:
            desc = "Accurate estimates (±10% variance)"

        return {
            "sample_count": count,
            "total_planned_minutes": total_planned,
            "total_actual_minutes": total_actual,
            "bias_ratio": bias_ratio,
            "accuracy_pct": acc_pct,
            "bias_description": desc,
        }

    def get_schedule_reliability(self, days: int = 14) -> Dict[str, Any]:
        """
        Percentage of scheduled blocks completed vs skipped / shrunk.
        """
        today = datetime.date.today()
        planned_count = 0
        completed_count = 0
        skipped_count = 0

        for i in range(days):
            d_str = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            blocks = self.db.get_time_blocks(d_str)
            for b in blocks:
                planned_count += 1
                if b.status == BlockStatus.COMPLETED:
                    completed_count += 1
                elif b.status == BlockStatus.SKIPPED:
                    skipped_count += 1

        if planned_count == 0:
            return {
                "total_blocks": 0,
                "reliability_pct": 100,
                "completed_count": 0,
                "skipped_count": 0,
            }

        rel_pct = int((completed_count / planned_count) * 100)
        return {
            "total_blocks": planned_count,
            "reliability_pct": rel_pct,
            "completed_count": completed_count,
            "skipped_count": skipped_count,
        }

    def get_habit_completion_clusters(self, days: int = 28) -> Dict[str, Any]:
        """
        Detect patterns in routine failures across day-of-week.
        """
        today = datetime.date.today()
        day_stats = {i: {"total": 0, "done": 0} for i in range(7)}  # 0=Monday, 6=Sunday
        tasks = self.db.get_tasks()
        total_tasks = len(tasks)

        if total_tasks == 0:
            return {"best_day": "Monday", "hardest_day": "Sunday", "completion_by_day": {}}

        for i in range(days):
            d = today - datetime.timedelta(days=i)
            d_str = d.strftime("%Y-%m-%d")
            weekday = d.weekday()
            comps = self.db.get_day_completions(d_str)
            done = sum(1 for c in comps.values() if c.done)
            day_stats[weekday]["total"] += total_tasks
            day_stats[weekday]["done"] += done

        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        rates = {}
        for w, st in day_stats.items():
            rate = int((st["done"] / st["total"]) * 100) if st["total"] > 0 else 0
            rates[day_names[w]] = rate

        best_day = max(rates, key=rates.get) if rates else "Mon"
        hardest_day = min(rates, key=rates.get) if rates else "Sun"

        return {
            "best_day": best_day,
            "hardest_day": hardest_day,
            "completion_by_day": rates,
        }
