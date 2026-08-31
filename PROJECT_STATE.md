# lifeOS v3 Execution Operating System — Full Project State Report

> **Generated:** 2026-08-31
> **Project:** `ajtui` (lifeOS v3 Execution Operating System)
> **Version:** 3.0.0
> **Runtime:** Python 3.14.7 (project venv at `.venv/`)
> **Test Status:** ✅ 31/31 passing (pytest, 9.35s)

---

## 1. Executive Summary & Mission
**lifeOS v3** is a local-first terminal execution operating system that converts weekly outcomes into daily commitments, turns commitments into protected focus blocks, records the truth, and uses that history to make tomorrow more realistic.

### Core Workflows:
1. **Today Command Center (`TodayScreen`)**: Single NOW card, Today's Three outcome-bearing priorities, deep work capacity budget, compact routines strip, and quick capture status.
2. **Projects & Actions Screen (`ProjectScreen`)**: Brutally simple hierarchy with active outcomes, startable NEXT actions (with estimates), WAITING actions with dependency blockers, and someday parking.
3. **Operational Plan Timeline (`PlanScreen`)**: Hourly timeline visualizer with 1-keystroke scheduling (`B` key), collision validation, and buffer management.
4. **Focus Cockpit (`FocusCockpitModal`)**: Narrowed distraction-free cockpit with live MM:SS countdown timer, live breadcrumb notes, and distraction capture (`I`).
5. **Missed Blocks Flow (`MissedBlockModal`)**: Enforces reality with 3 explicit choices: `[R] reschedule`, `[S] shrink`, or `[C] cancel / skip with reason`.
6. **90-Second Daily Close (`DailyCloseModal`)**: Structured retrospective appending cleanly to that day's plain-text journal file and auto-priming tomorrow's first step.
7. **Deterministic Analytics Engine (`AnalyticsEngine`)**: Pure Python & SQLite calculation of estimate accuracy bias, schedule reliability, and habit failure clusters.
8. **Narrow AI Copilot (`AIService` & `AIDraftModal`)**: OpenRouter integration using `google/gemini-2.5-flash-lite` for daily summaries, tomorrow planning, and inbox triage with strict human-in-the-loop review.
9. **Sunday Weekly Review (`ReviewScreen`)**: Retrospective answering outcome accuracy, pattern insights, and interactive decisions checklist.
10. **Command Palette (`:`) & Help Overlay (`?`)**: Searchable command launcher and keyboard shortcuts matrix.

---

## 2. Directory Structure & Architecture

```
lifeOS v3 (Textual App)
├── lifeos/
│   ├── app.py                   ← DailyOS master App (composition + keys + state)
│   ├── __main__.py              ← `python -m lifeos` entrypoint
│   ├── __init__.py              ← Public API exports (version 3.0.0)
│   ├── core/
│   │   ├── models.py            ← Typed domain models (Project, Action, TimeBlock, DailyPriority, InboxItem)
│   │   ├── analytics.py         ← Pure deterministic execution analytics (bias, reliability)
│   │   └── ai.py                ← Narrow AI Copilot (OpenRouter Gemini 2.5 Flash Lite + offline fallback)
│   ├── db/
│   │   ├── local.py             ← SQLite schema migrations, CRUD, capacity budget, journal mirror
│   │   └── supabase_sync.py     ← Realtime WebSocket subscriber + outbox synchronization
│   └── ui/
│       ├── themes.py            ← 3 Curated themes (lifeos, phosphor, amber), dynamic tokens & CSS
│       ├── widgets.py           ← Reusable UI widgets (HeaderBar, KeyChipBar, MonthCalendarView, etc.)
│       ├── today_screen.py      ← Today Command Center (Now card, Today's Three, Capacity budget)
│       ├── project_screen.py    ← Projects & Next Actions hierarchy screen
│       ├── plan_screen.py       ← Operational Plan Day Timeline screen
│       ├── review_screen.py     ← Sunday Weekly Review screen
│       ├── journal_screen.py    ← Dual-mirrored plain-text journal reader/editor/browser
│       ├── focus_cockpit.py     ← Live focus session countdown & notes modal
│       ├── missed_block_modal.py← Explicit missed block handler modal
│       ├── schedule_modal.py    ← 1-Keystroke block scheduler modal
│       ├── capture_modal.py     ← Global 2-second quick capture modal
│       ├── close_modal.py       ← 90-Second daily close retrospective modal
│       ├── ai_modal.py          ← Human-in-the-loop AI draft review modal
│       ├── command_palette.py   ← Searchable command launcher (:)
│       └── help_modal.py        ← Searchable keybindings matrix (?)
├── supabase/schema.sql          ← Postgres schema with RLS and realtime publication
├── tests/                       ← Comprehensive test suite (31 tests)
│   ├── test_daily_legacy.py     ← Legacy routine, undo, and realtime sync tests
│   ├── test_lifeos.py           ← Core SQLite, outbox, and journal mirror tests
│   ├── test_phase1_execution.py ← Phase 1 invariants (max 3, physical actions, capacity budget)
│   ├── test_phase2_planning.py  ← Phase 2 timeline, focus cockpit, missed blocks, weekly review
│   ├── test_phase3_intelligence.py ← Deterministic analytics and AI draft review tests
│   └── test_ui_flow.py          ← Textual headless navigation and async UI tests
├── demo_v3_loop.py              ← End-to-end headless verification demo
├── DECISIONS.md                 ← Product choices, invariants, tradeoffs & model selection
├── README.md                    ← Root documentation and user guide
└── pyproject.toml / requirements.txt / .env
```

---

## 3. Test Suite Verification

Run all test suites with:
```bash
.venv/bin/python -m pytest
```

Output:
```
============================== 31 passed in 9.35s ==============================
```
