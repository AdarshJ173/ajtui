# Prompt — paste everything below the line into your agent (run it from the repo root, with PROJECT_STATE.md present)

---

You are a world-class product engineer and the architect of this repository. Use your full intelligence, think critically, challenge weak ideas in this spec where your judgment is better — and state it when you do. Your mission: **evolve lifeOS Daily from a habit tracker into an intent-to-execution operating system** — a system that decides what matters today, reserves time for it, makes starting frictionless, captures evidence of what happened, and improves tomorrow's plan. Not a surveillance dashboard. Not a second brain. An execution system.

Product definition to hold in your head at all times:
> lifeOS is a local-first terminal execution system that converts weekly outcomes into daily commitments, turns commitments into protected focus blocks, records the truth, and uses that history to make tomorrow more realistic.

## PHASE 0 — Ground truth & foundation repair (before ANY new feature)

1. Read `PROJECT_STATE.md` in the repo root first. Then run `codegraph lifeos` to refresh the dependency graph and use it as your source of truth for blast radius before every refactor. Keep it re-synced at each phase end.
2. Fix the known architectural debts (from PROJECT_STATE.md §16) — all of them, in this order:
   - **Realtime**: implement actual Supabase Realtime subscriptions (the `_realtime_channel` in `supabase_sync.py` is declared but never set up; sync is currently 25s polling). Subscriptions become the primary inbound path; retain polling only as reconnect/catch-up protection. On socket reconnect, do a catch-up pull — never trust the socket alone.
   - **Dead code**: delete or fully integrate `lifeos/ui/tasks_screen.py` (unused duplicate) and `lifeos_theme.py` (stale 800-line theme copy). One source of truth per concern. Verify nothing imports them.
   - **Split `app.py`**: `DailyOS` currently does view composition + primary control. Refactor into `AppShell` (routing, commands, global state) + real screens: `TodayScreen`, `JournalScreen`, `ProjectScreen`, `PlanScreen`, `ReviewScreen`. Introduce repository/service interfaces so SQLite, sync, and UI never couple through `self.app`.
   - **Warnings & hygiene**: fix the un-awaited `call_from_thread` RuntimeWarning; enforce toast TTL (`AnimTuning.toast_ttl` exists but toasts never auto-clear — wire the existing `toast_*` Messages); add **undo** for task deletion (soft-delete already exists — expose a 5s undo toast); add the root `README.md` that `pyproject.toml` declares.
   - **Tests**: consolidate the legacy `test_daily.py` path into the pytest suite; add integration tests for outbox / reconnect / realtime behavior. All existing 17 tests must still pass.
3. Gate: do not proceed to Phase 1 until the suite is green, the tree is clean of dead code, and realtime subscriptions demonstrably deliver a remote change without a poll cycle. Prove it with a test or a scripted demo.
4. Commit Phase 0 separately with a clear message.

## PHASE 1 — Execution MVP

The model upgrade. Habits are not projects, projects are not tasks, tasks are not calendar blocks. Keep habits (the existing ritual loop) exactly as-is, subordinate to the new execution layer. The hierarchy:

```
Areas        Health | Career | Learning | Relationships | Admin
  └ Projects       "Dyzeee release" | "ML foundations"
      └ Outcomes   "Publish v0.1"  | "Finish Week 1"
          └ Actions "Implement OAuth redirect" | "Complete lesson 3"
              └ Blocks  09:00–10:30 Deep Work
Habits             recurring daily/weekly behaviors (existing system)
Journal            evidence, thinking, review (existing system)
```

### New data model (additive migrations only; every table gets uuid/updated_at/dirty/deleted + outbox + Supabase mirror + RLS + realtime, consistent with the existing sync engine)

```sql
projects            id, uuid, title, area, status, outcome, deadline?, created_at, updated_at, archived_at
actions             id, uuid, project_id?, title, status, estimate_minutes,
                    energy_level, context, due_date?, scheduled_date?,
                    completed_at, created_at, updated_at
action_dependencies action_id, blocked_by_action_id
daily_priorities    id, uuid, date, action_id, rank (1–3), committed_at
time_blocks         id, uuid, date, starts_at, ends_at, action_id?, kind,
                    planned_minutes, actual_minutes?, status, notes?
inbox_items         id, uuid, content, captured_at, source, status,
                    linked_project_id?, converted_action_id?, resolved_at?
```

Constrained statuses — enforce at the repository layer:
- Project: `active | someday | waiting | completed | archived`
- Action: `inbox | next | scheduled | doing | waiting | done | cancelled`
- Block: `planned | active | completed | skipped | overrun`

Invariants (hard rules, tested):
- An **active project must always expose at least one concrete, startable next action**. Never allow "do the project" as an action title — reject vague actions at creation with a hint ("what is the next physical action?").
- `daily_priorities` allows **at most 3 ranks per date** — enforce with a constraint.
- A priority cannot be committed unless its action has an `estimate_minutes` and a non-empty title describing a physical action.

### [1] TODAY — Command Center (replaces the routine-only home screen)

```
◆ lifeOS                    MON, AUG 31 · 13:38       ☁ LIVE · 🔥 4

NOW ─────────────────────────────────────────────────────────────
  13:45–15:15  ◉ Build lifeOS Planner                    [START]
  Next physical action: define project/action/block schema

TODAY'S THREE ───────────────────────────────────────────────────
  1. [ ] lifeOS planner data model                90m · Deep work
  2. [ ] ML mathematics: lesson 3                 60m · Learning
  3. [ ] Cardio / strength                        45m · Health

COMMITMENTS          ROUTINES             CAPTURE
  2h 15m planned     1/6 complete         [I] inbox: 4
  1h 45m available   ▰▰▱▱▱▱ 17%           "Anything on your mind?"
```

Rules:
- Exactly **one** Now card, ever. It shows the current/next block or, if none, the top unblocked next action. Never six equally urgent choices.
- Today's Three: at most 3 outcome-bearing priorities. Other actions live in Projects.
- Capacity budget: a day has a deep-work capacity (default 3h30m, configurable). Commitments vs. available shown. Warn (amber) when over-committed; never let the UI imply 8h of cognitive work fits in 8h.
- Routines remain visible but visually subordinate — a compact strip, not the hero. Checking "read 15 pages" must never look equivalent to shipping a project artifact.
- The existing ritual list adapts into this layout; when few routines exist, space goes to Now / Today's Three / blocks — never a barren void.

### [2] PROJECTS screen

Brutally simple, not a Notion clone:

```
PROJECT: lifeOS Planner MVP                    active · Career
Outcome: Plan today in <5 minutes and finish a focused block.

NEXT
  [ ] Define SQLite schema for projects/actions/blocks      35m
  [ ] Build Today Command Center                            90m
  [ ] Add action-to-block scheduling                        75m

WAITING
  [ ] Decide calendar-provider integration                 blocked
```

Full CRUD for projects and actions; reorder; promote/demote action status; `someday` parking; archive. Blocked actions render dim with their blocker. Every project shows outcome + next action at a glance.

### Global capture — `I` from any screen

```
CAPTURE ─────────────────────────────────────────────────────────
  > Need to compare OpenRouter fallbacks for agent workflow

  [Enter] save inbox    [P] attach project    [A] make next action
```

Two seconds max, zero categorization theatre: no tags, no folders, no metadata. Inbox is processed only during daily close / weekly review into exactly four destinations: next action, project, calendar block, or delete/archive.

### Daily close — `X` close day (90-second flow)

```
CLOSE DAY · MON AUG 31

EXECUTION
  Planned deep work: 3h 30m     Actual: 2h 10m
  Priorities completed: 1 / 3   Routines: 4 / 6

1. What moved forward?
   > _
2. What blocked me?
   > _
3. What is tomorrow's first action?
   > _

[Enter] append to journal    [P] plan tomorrow
```

Appends to that day's existing plain-text journal as readable text with simple separators (NO markdown syntax). Tomorrow's first action is auto-offered as tomorrow's Now card.

**Gate**: all Phase 1 features CRUD-clean, synced, tested. Commit separately.

## PHASE 2 — Planning MVP

### [3] PLAN screen — operational day timeline

```
MON AUG 31                                  capacity: 3h 30m / 4h

08:00 ┌────────────────────────────────────────────────────────┐
      │ Morning reset                               routine     │
09:00 ├──────── Deep Work: lifeOS planner ───────── 90m ────────┤
10:30 │ Buffer / admin                                          │
11:00 ├──── ML mathematics: Lesson 3 ────────────── 60m ────────┤
12:00 │ Lunch / walk                                            │
14:00 ├── Cardio / strength ─────────────────────── 45m ────────┤
      └────────────────────────────────────────────────────────┘
```

Mechanics:
- One keystroke scheduling: select action → `B` block → pick start + duration. Auto-insert buffers; refuse impossible stacking.
- **Block start → focus cockpit**: the app narrows to task, countdown timer, remaining time, minimal session notes, and a distraction-capture key (dumps a stray thought into inbox without leaving the cockpit).
- **Missed blocks never silently roll to tomorrow.** Present exactly three choices: `[R] reschedule · [S] shrink · [C] cancel`. Reality must enter the system.
- Block end: `completed / partial / skipped`, record `actual_minutes`, one-line reason if skipped.
- Track planned-vs-actual per estimate — this history feeds Phase 3 (estimate-bias correction).

### [W] Weekly review (Sundays) — answers only decision-triggering questions

```
WEEK 35 REVIEW

OUTCOMES
  Active projects: 3             Finished outcomes: 1
  Deep work: 9h 40m / 12h planned   Accuracy: 81%

PATTERNS
  Best start window: 09:00–11:00
  Most skipped block: post-lunch admin
  Habit failure cluster: sleep + morning start

DECISIONS
  [ ] Keep active: lifeOS, ML foundations
  [ ] Pause: content experimentation
  [ ] Protect 09:00–11:00 Mon–Fri as deep work
  [ ] Move cardio to 18:00 on class days
```

**Gate**: full loop works — plan day → start block → focus → close block → close day → weekly review. Commit separately.

## PHASE 3 — Intelligence (deterministic first, AI second)

1. **Deterministic analytics first** (pure SQL/python over local data, zero AI): completion by hour/day, estimate accuracy, schedule reliability, habit-failure associations.
2. **AI, used narrowly** — only where it compresses a costly cognitive task. Provider: OpenRouter via env var (`OPENROUTER_API_KEY`, `LIFEOS_AI_MODEL`, sensible default), offline-degraded gracefully, never on the render path. Every AI output is a **draft with evidence citations and an explicit accept/reject key** — no autonomous mutation of tasks/calendar/journal, ever.

| Feature | Build? | Role |
|---|---|---|
| Journal daily summary | ✅ | Extract events, decisions, commitments, open loops; show draft; never silently rewrite the journal |
| Tomorrow planner | ✅ | Open actions + unfinished blocks + capacity → proposed 3-priority plan |
| Weekly pattern brief | ✅ | Repeated misses, estimate bias, time/energy patterns; cite source days |
| Inbox parser | ✅ | Suggest action/project/block/archive; user confirms |
| Autonomous task creation | ❌ | Drafts only; I decide |
| Notification intelligence | ❌ | Noise at this stage |
| Mood/relationship inference | ❌ | Weak evidence, false confidence |
| AI-written journal in my voice | ❌ | Recap drafts only |

Interface:

```
AI > Plan tomorrow from my current projects.
AI > Proposed:
     1. 09:00–10:30 — Finish actions/time_blocks migration
     2. 11:00–12:00 — ML lesson 3
     3. 18:00–18:45 — Strength workout
     I deferred "YouTube research" because it has no next action.
     [A]ccept  [E]dit  [R]egenerate

AI > What has caused me to skip cardio lately?
AI > 4 of 5 skips followed a 14:00 block after <6h 30m sleep.
     Recommendation: move it to 18:00 on class days.
     Evidence: Aug 18, 21, 24, 28.
     [A]pply schedule rule   [D]ismiss
```

Commit separately.

## UI/UX system rules (apply across all new screens)

- Keep the phosphor identity, one-line density, fixed-width calendar, glyph system, instant local-first feel, and visible sync state.
- **Color is meaning, never decoration**: mint = complete/live/available · amber = needs decision/at-risk/partial · magenta-red = conflict/overdue/blocked · cyan = navigational focus/active context · dim gray = historical.
- Quieter selection: thin left rail + subtle tinted band, not a saturated row.
- History as evidence, not gamification: a 14-day heatmap beats another streak flame.
- Animations stay micro and informative (progress fill, focus transition, completion settle). Retain the single animation timer and reduced-motion capability. Nothing animates continuously.
- **Command palette**: `:` opens `today / plan / capture / project add / journal / review / sync / theme …` — this scales; the footer chip bar must not grow to 25 chips.
- **`?` help overlay**: searchable by command. Keyboard density grows fast with projects/blocks/reviews — discoverability is a feature.
- Footer chips: only the 6–8 most common actions for the current mode.

## Non-negotiables

- Zero regressions: every existing feature, keybinding, theme, animation, and test keeps working. Additive-only SQLite migrations; the sync engine extends to new tables with the same outbox/LWW/journal-protection guarantees.
- Local-first everywhere: all new features fully functional offline; sync is background-only; no network on any render path.
- Secrets: env/`.env` only, never code/logs/git. AI calls degrade to "offline — local only" without crashing.
- Constrained statuses and invariants enforced at the repository layer with tests, not by UI convention.
- Every phase ends green: pytest suite (old + new) passing, `codegraph lifeos` re-synced, clean commit per phase.

## Explicitly out of scope — do NOT build any of this

WhatsApp/email/notification ingestion · health/screen-time dashboards · knowledge graph · pomodoro variants · mood scores · social features · tags/folders/metadata systems · autonomous agents that change my calendar or tasks · a mobile client. Tempting, technically interesting, and not the bottleneck. The bottleneck is turning intentions into protected blocks, starting the right task, and reviewing why plans diverge from reality.

## Final deliverables

1. The complete working codebase, one clean commit per phase (0, 1, 2, 3)
2. Updated `supabase/schema.sql` with all new tables, RLS, realtime publication
3. Updated `README.md` + `PROJECT_STATE.md` reflecting v3 architecture
4. Test report: old suite green + new tests (invariants, missed-block flow, undo, realtime subscription, outbox/reconnect, daily close append, weekly review computation)
5. `DECISIONS.md`: ≤10 bullets — where you deviated from this spec on your own judgment, and why
6. A short demo script I can run to see: plan a day → block an action → focus cockpit → close block → close day → weekly review → AI tomorrow-plan

Build it like this becomes the system I open every morning for years. Ship it.
