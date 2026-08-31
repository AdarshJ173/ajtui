"""
lifeOS Narrow AI Copilot Service
================================
Integrated via OpenRouter API with graceful offline fallback.
Strict human-in-the-loop: Every output is a draft with evidence citations.
Never autonomously mutates data.

Default Model: google/gemini-2.5-flash-lite (best-in-class reasoning at ultra-low cost)
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

import dotenv

DEFAULT_MODEL = "google/gemini-2.5-flash-lite"
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


class AIService:
    """Narrow cognitive copilot generating reviewable drafts."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        dotenv.load_dotenv()
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "").strip()
        self.model = model or os.getenv("LIFEOS_AI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)

    def _call_openrouter(self, system_prompt: str, user_prompt: str, max_tokens: int = 600) -> Optional[str]:
        """Send prompt to OpenRouter with timeout and fallback."""
        if not self.api_key:
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/AdarshJ173/ajtui",
            "X-Title": "lifeOS Execution System",
        }
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }

        try:
            req = urllib.request.Request(
                OPENROUTER_ENDPOINT,
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    choices = data.get("choices", [])
                    if choices:
                        return choices[0]["message"]["content"].strip()
        except Exception:
            return None
        return None

    # -----------------------------------------------------------------------
    # 1. Journal Daily Summary
    # -----------------------------------------------------------------------

    def summarize_daily_journal(self, journal_content: str, date_str: str) -> Dict[str, Any]:
        """Extract events, decisions, commitments, and open loops from journal."""
        if not journal_content.strip():
            return {
                "available": False,
                "summary": "No journal content recorded for this day.",
                "evidence": date_str,
            }

        sys_p = (
            "You are lifeOS Journal Synthesizer. Analyze the user's daily journal and extract: "
            "1. Key Events\n2. Decisions Made\n3. Commitments\n4. Open Loops\n"
            "Keep it concise and evidence-based. No fluff or flattery."
        )
        user_p = f"Date: {date_str}\n\nJournal Content:\n{journal_content}"

        res = self._call_openrouter(sys_p, user_p, max_tokens=400)
        if res:
            return {
                "available": True,
                "summary": res,
                "evidence": f"Journal entry on {date_str} ({len(journal_content.split())} words)",
            }

        # Offline deterministic fallback
        lines = [l.strip() for l in journal_content.split("\n") if l.strip()]
        return {
            "available": True,
            "summary": f"Local Summary:\n- Recorded {len(lines)} notes ({len(journal_content.split())} words)\n- First note: {lines[0] if lines else 'None'}",
            "evidence": f"Local file ({date_str}.txt)",
        }

    # -----------------------------------------------------------------------
    # 2. Tomorrow Planner
    # -----------------------------------------------------------------------

    def propose_tomorrow_plan(
        self,
        projects: List[Any],
        uncompleted_actions: List[Any],
        capacity_minutes: int = 210,
    ) -> Dict[str, Any]:
        """Propose 3 outcome-bearing daily priorities fitting the capacity budget."""
        proj_context = "\n".join([f"- Project: {p.title} (Outcome: {p.outcome})" for p in projects[:5]])
        act_context = "\n".join([f"- Action: {a.title} ({a.estimate_minutes}m, Project: {a.project_title or 'General'})" for a in uncompleted_actions[:8]])

        sys_p = (
            "You are lifeOS Tomorrow Planner. Propose exactly 3 outcome-bearing daily priorities for tomorrow. "
            "Ensure the total estimated minutes fit within the capacity budget (default 210 minutes = 3h 30m). "
            "For each priority specify: Rank (1-3), Title, Estimate in minutes, and Project Name. "
            "Cite why this was prioritized."
        )
        user_p = f"Capacity: {capacity_minutes} minutes\n\nActive Projects:\n{proj_context}\n\nCandidate Actions:\n{act_context}"

        res = self._call_openrouter(sys_p, user_p, max_tokens=450)
        if res:
            return {
                "available": True,
                "proposal": res,
                "evidence": f"Derived from {len(projects)} active projects & {len(uncompleted_actions)} open actions",
            }

        # Offline deterministic fallback: pick top 3 unblocked actions
        items = []
        tot = 0
        for idx, a in enumerate(uncompleted_actions[:3], start=1):
            items.append(f"{idx}. {a.title} ({a.estimate_minutes}m) · {a.project_title or 'General'}")
            tot += a.estimate_minutes

        fallback_text = "Proposed 3 Priorities:\n" + "\n".join(items) + f"\n\nTotal: {tot}m / {capacity_minutes}m budget."
        return {
            "available": True,
            "proposal": fallback_text,
            "evidence": "Deterministic ranking from active next actions",
        }

    # -----------------------------------------------------------------------
    # 3. Weekly Pattern Brief
    # -----------------------------------------------------------------------

    def generate_weekly_pattern_brief(self, analytics_data: Dict[str, Any]) -> Dict[str, Any]:
        """Synthesize repeated misses, estimate bias, and schedule reliability citing evidence."""
        sys_p = (
            "You are lifeOS Pattern Analyst. Synthesize the user's execution history into a 3-bullet pattern brief: "
            "1. Deep work efficiency & estimate accuracy\n"
            "2. Failure patterns & skipped time windows\n"
            "3. One actionable schedule rule recommendation\n"
            "Cite the provided numbers as evidence."
        )
        user_p = f"Analytics Data:\n{json.dumps(analytics_data, indent=2)}"

        res = self._call_openrouter(sys_p, user_p, max_tokens=400)
        if res:
            return {
                "available": True,
                "brief": res,
                "evidence": f"Computed over {analytics_data.get('sample_count', 14)} past execution events",
            }

        bias_desc = analytics_data.get("bias_description", "Accurate estimates")
        return {
            "available": True,
            "brief": f"- Estimate Accuracy: {bias_desc}\n- Schedule Reliability: {analytics_data.get('reliability_pct', 85)}% completed on time\n- Recommendation: Protect morning slots (09:00–11:00) as deep work",
            "evidence": "Deterministic local metrics",
        }

    # -----------------------------------------------------------------------
    # 4. Inbox Parser
    # -----------------------------------------------------------------------

    def parse_inbox_item(self, content: str, active_projects: List[str]) -> Dict[str, Any]:
        """Suggest destination: next action, project, calendar block, or archive."""
        sys_p = (
            "You are lifeOS Inbox Parser. Given a raw captured thought, classify it into one destination: "
            "destination: 'action' | 'project' | 'block' | 'archive'. "
            "Provide: cleaned_title (concrete physical step), estimate_minutes (integer), and suggested_project (from active list if matched). "
            "Return JSON only: {\"destination\": \"action\", \"title\": \"...\", \"estimate_minutes\": 30, \"project\": \"...\"}"
        )
        user_p = f"Captured thought: '{content}'\nActive projects: {json.dumps(active_projects)}"

        res = self._call_openrouter(sys_p, user_p, max_tokens=250)
        if res:
            try:
                # Find JSON block
                clean_json = res.strip()
                if clean_json.startswith("```"):
                    clean_json = clean_json.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                parsed = json.loads(clean_json)
                return {
                    "available": True,
                    "destination": parsed.get("destination", "action"),
                    "title": parsed.get("title", content),
                    "estimate_minutes": parsed.get("estimate_minutes", 30),
                    "project": parsed.get("project"),
                    "raw": res,
                }
            except Exception:
                pass

        # Offline deterministic fallback
        return {
            "available": True,
            "destination": "action",
            "title": content,
            "estimate_minutes": 30,
            "project": None,
            "raw": "Local classification: Next Action (30m)",
        }

    # -----------------------------------------------------------------------
    # 5. Daily Close Retrospective Generator
    # -----------------------------------------------------------------------

    def generate_daily_close_draft(self, day_stats: Dict[str, Any]) -> Dict[str, str]:
        """Generate a structured daily close reflection (forward, blocked, tomorrow)."""
        sys_p = (
            "You are lifeOS Daily Close Retrospective generator. Given the day's execution telemetry "
            "(deep work minutes, priorities completed, routines completed, actions finished/uncompleted), "
            "synthesize a concise, truth-based daily close summary. "
            "Return JSON only: {\"forward\": \"...\", \"blocked\": \"...\", \"tomorrow\": \"...\"}\n"
            "Guidelines: No flattery, factual truth only. 'tomorrow' must be a concrete, startable physical step."
        )
        user_p = (
            f"Date: {day_stats.get('date')}\n"
            f"Planned Deep Work: {day_stats.get('planned_str')} | Actual: {day_stats.get('actual_str')}\n"
            f"Priorities Done: {day_stats.get('priorities_done')}/{day_stats.get('priorities_total')}\n"
            f"Routines Done: {day_stats.get('routines_done')}/{day_stats.get('routines_total')}\n"
            f"Completed Actions: {json.dumps(day_stats.get('done_actions', []))}\n"
            f"Uncompleted Actions: {json.dumps(day_stats.get('uncompleted_actions', []))}\n"
        )

        res = self._call_openrouter(sys_p, user_p, max_tokens=300)
        if res:
            try:
                clean_json = res.strip()
                if clean_json.startswith("```"):
                    clean_json = clean_json.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                parsed = json.loads(clean_json)
                if "forward" in parsed and "tomorrow" in parsed:
                    return {
                        "forward": parsed.get("forward", ""),
                        "blocked": parsed.get("blocked", "None"),
                        "tomorrow": parsed.get("tomorrow", ""),
                    }
            except Exception:
                pass

        # Deterministic fallback
        done_actions = day_stats.get("done_actions", [])
        uncompleted = day_stats.get("uncompleted_actions", [])
        r_done = day_stats.get("routines_done", 0)

        forward = ", ".join(done_actions) if done_actions else f"{r_done} routine habits maintained"
        blocked = "None" if not uncompleted else f"Pending uncompleted: {', '.join(uncompleted)}"
        tomorrow = uncompleted[0] if uncompleted else "Define and commit top 3 daily priorities"

        return {
            "forward": forward,
            "blocked": blocked,
            "tomorrow": tomorrow,
        }
