# lifeOS v3 Architecture & Product Decisions

## 1. Product Philosophy & Definition
> **"lifeOS is a local-first terminal execution system that converts weekly outcomes into daily commitments, turns commitments into protected focus blocks, records the truth, and uses that history to make tomorrow more realistic."**

Prior to v3, lifeOS Daily was primarily a habit tracker with a mirrored journal. In v3, habits are retained in a compact, subordinate strip, while the primary viewport becomes the **Today Command Center**, orchestrating the full execution loop:
`Outcome -> Next Action -> Today's Three -> Operational Timeline Block -> Focus Cockpit -> Daily Close -> Weekly Review`.

---

## 2. Hard Invariants & Guardrails

### 2.1 Daily Priorities Cap (`max 3`)
- **Decision**: SQLite enforces `CHECK(rank BETWEEN 1 AND 3)` and `UNIQUE(date, rank)` on the `daily_priorities` table.
- **Rationale**: Overcommitting dilutes focus and causes planning fiction. 3 commitments per day is the human cognitive limit for deep-work throughput.

### 2.2 Concrete Physical Action Validation
- **Decision**: Actions cannot be created or committed without passing physical action validation (`is_valid_physical_action()`) and must have `estimate_minutes > 0`.
- **Rationale**: Vague entries like `"work on project"` or `"study"` stall initiation in the terminal. Enforcing concrete verbs (e.g. `"Implement WebSocket multiplexer in telemetry.py"`) guarantees zero friction at the moment of execution.

### 2.3 Explicit Missed Block Resolution
- **Decision**: Missed time blocks never silently roll to tomorrow. The system forces exactly 3 explicit choices via `MissedBlockModal`: `[R] reschedule`, `[S] shrink`, or `[C] cancel / skip with reason`.
- **Rationale**: Unaddressed missed blocks corrupt historical analytics. Reality must enter the system.

### 2.4 Journal Protection & Readable Close Formatting
- **Decision**: Daily close and weekly review append to the plain-text journal file with clean whitespace dividers and NO markdown syntax clutter (`#`, `**`).
- **Rationale**: The user's journal is a human sacred record; the execution OS must never overwrite, clobber, or clutter existing personal writing.

---

## 3. OpenRouter Model Selection

- **User Directive**: `"best yet most cheapeset model only , i repeat again , best of the best and most cheapest model for our usecase"`
- **Selected Model**: `google/gemini-2.5-flash-lite` via OpenRouter.
  - **Cost**: $0.10 / million prompt tokens, $0.40 / million completion tokens.
  - **Speed & Context**: Sub-second latency, 1,000,000 token context window.
  - **Reasoning**: State-of-the-art structured extraction and concise synthesis for daily journal summaries, tomorrow planning, and inbox triage.
- **Strict Human-in-the-Loop (HITL)**:
  - Every AI output is presented in an interactive `AIDraftModal` with evidence citations and explicit actions: `[A]ccept`, `[E]dit`, `[R]egenerate`, `[D]ismiss`.
  - The AI **never** autonomously creates or mutates calendar blocks, priorities, or tasks without explicit user approval.
  - Graceful offline degradation: If `OPENROUTER_API_KEY` is absent or the network drops, the system runs local deterministic ranking without crashing.

---

## 4. Subsystems & Architectural Debt Inventory

| Subsystem / Component | v2 State | v3 Architecture | Key Fixes / Debt Retired |
|---|---|---|---|
| **Theme System** | Redundant 800-line `lifeos_theme.py` duplicate | Single source of truth in `lifeos/ui/themes.py` | Deleted `lifeos_theme.py`; dynamic terminal color token mapper |
| **Cloud Sync** | Sync PostgREST without Realtime WebSocket | Supabase Realtime WebSocket listener on background event loop | Async WebSocket client thread with catch-up pull and 25s polling fallback |
| **Tasks & Actions** | Habits only (`tasks` table) | Typed hierarchy: `projects`, `actions`, `action_dependencies`, `daily_priorities`, `time_blocks`, `inbox_items` | Full schema migrations in SQLite & Postgres RLS |
| **Planning & Focus** | None (Habit grid only) | Operational day timeline (`PlanScreen`) + narrowed `FocusCockpitModal` | Countdown timer, live notes, distraction capture (`I`), planned vs actual minutes tracking |
| **Analytics & Review** | None | Pure deterministic analytics (`AnalyticsEngine`) + Sunday `ReviewScreen` | Estimate bias ratio, schedule reliability, habit failure clusters |
| **Navigation & Help** | Static key hints | Command palette (`:`) and Searchable Help Overlay (`?`) | Discoverability for all 15+ keyboard actions |
