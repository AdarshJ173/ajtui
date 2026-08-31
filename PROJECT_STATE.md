# lifeOS Daily — Full Project State Report

> **Generated:** 2026-08-31
> **Project:** `ajtui` (lifeOS Daily)
> **Version:** 2.0.0
> **Repo:** https://github.com/AdarshJ173/ajtui.git (branch `main`, up-to-date with `origin/main`)
> **Runtime:** Python 3.14.7 (project venv at `.venv/`)
> **Test status:** ✅ 17/17 passing (pytest, 9.41s)

---

## 1. What Is This Project?

**lifeOS Daily** is a state-of-the-art **terminal (TUI) routine / habit / momentum tracker with an integrated daily journal and cloud sync**. It is built on the [Textual](https://textual.textualize.io) framework (a modern async TUI library) and [Rich](https://rich.readthedocs.io) for styled text, backed by **SQLite** locally and **Supabase** (PostgreSQL) in the cloud.

It is a single-user, local-first, "one living document per day" productivity tool that runs entirely in the terminal. It tracks daily rituals (habits), computes streaks and monthly completion statistics, shows a live calendar with completion "semaphores," maintains a dual-mirrored plain-text journal, and syncs everything to the cloud with an offline-tolerant outbox queue.

### Value Proposition (non-technical)
- **Zero-latency**: every keystroke applies instantly; the UI never blocks on the network.
- **Works offline**: you can use it fully without any connection; changes queue and replay later.
- **Your data stays readable**: journals are plain `.txt` files you can open in Vim/VS Code, not a locked database.
- **No silent data loss**: conflicting journal edits are never discarded — the loser is archived.
- **Beautiful by default**: three curated themes, animated boot, eased progress bars, live clock, streak "flame."

---

## 2. High-Level Architecture

```
lifeOS Daily (Textual App)
├── lifeos/                      ← the real, modular package (source of truth)
│   ├── app.py                   ← DailyOS master App (composition + keys + state)
│   ├── __main__.py              ← `python -m lifeos` entrypoint
│   ├── __init__.py              ← public API exports (version 2.0.0)
│   ├── core/
│   │   └── models.py            ← dataclasses: Task, Completion, JournalEntry, SyncState
│   ├── db/
│   │   ├── local.py             ← SQLite + journal .txt mirror + outbox queue
│   │   └── supabase_sync.py     ← background sync engine (push/pull/conflicts)
│   └── ui/
│       ├── themes.py            ← theme engine (palettes, glyphs, CSS, animations)
│       ├── widgets.py           ← reusable crafted widgets (list, calendar, dock, …)
│       ├── journal_screen.py    ← journal read/edit/browse screen
│       └── tasks_screen.py      ← ⚠ legacy TasksScreen (unused)
├── supabase/schema.sql          ← cloud schema + RLS + realtime publication
├── tests/                       ← pytest suite (17 tests)
├── daily.py                     ← legacy backwards-compat entrypoint proxy
├── test_daily.py                ← legacy standalone self-test script
├── lifeos_theme.py              ← ⚠ legacy standalone theme copy (unused)
├── codegraph.html               ← generated code-dependency visualization (artifact)
├── SYNC.md                      ← sync architecture documentation
├── pyproject.toml / requirements.txt / .env / .gitignore
```

### Module Dependency Graph (from `codegraph --object-only lifeos`)

- `lifeos/__init__.py` → `models`, `local`, `app`
- `lifeos/__main__.py` → `app.main`
- `lifeos/app.py` (class `DailyOS`) → `widgets.*`, `models.*`, `journal_screen.JournalScreen`, `themes.*`, `local.DatabaseManager`, `supabase_sync.SupabaseSyncEngine`, `App`
- `lifeos/core/__init__.py` → `models`
- `lifeos/core/models.py` → `SyncStateEnum`, `str`, `Enum` (leaf dataclasses otherwise)
- `lifeos/db/__init__.py` → `local`
- `lifeos/db/local.py` (`DatabaseManager`) → `models.{Task, Completion, JournalEntry, current_iso_time, generate_uuid}`
- `lifeos/db/supabase_sync.py` (`SupabaseSyncEngine`) → `models.{SyncState, SyncStateEnum, current_iso_time}`
- `lifeos/ui/__init__.py` → `widgets`, `themes`, `tasks_screen`, `journal_screen`
- `lifeos/ui/journal_screen.py` → `widgets.{HeaderBar,ToastRail,KeyChipBar,ConfirmModal}`, `themes.fit`, `Static`, `Screen`
- `lifeos/ui/tasks_screen.py` (`TasksScreen`) → `widgets.*`, `Screen`
- `lifeos/ui/themes.py` → `Theme` → `build_glyphs`, `TypeRamp`, `Spacing`, `Metrics`, `AnimTuning`, `Messages`, `_build_logo`, `_build_css`
- `lifeos/ui/widgets.py` → `themes.{ease_out_back, …}`, `models.{SyncStateEnum, Completion}`, `Static`, `ModalScreen`

**Key observation:** `DailyOS` (the App) composes all widgets directly in `app.py`. The `TasksScreen` class in `tasks_screen.py` is a **duplicate/legacy implementation that is not used at runtime.**

---

## 3. Package Structure & Entry Points

### 3.1 `lifeos/app.py` — `DailyOS(App)` (685 lines)
The master application class. It is **both** the app shell and the controller (it does not delegate to a separate screen for the main task view).

Responsibilities:
- **Startup**: resolves capabilities (color/unicode/motion), persists/reads theme, opens `DatabaseManager`, constructs `SupabaseSyncEngine`, sets initial state (current date, streak, month stats, sparkline, cursor, animation state).
- **Composition** (`compose()`): yields `HeaderBar`, `HeroBanner`, a `Horizontal` split of `TaskListView` + `MonthCalendarView`, `MomentumDock`, `ToastRail`, `KeyChipBar`, and a conditional `BootOverlay`.
- **Lifecycle**: `on_mount` starts the animator + sync engine, a 1s clock timer, optional ambient flicker timer, applies responsive layout mode, and starts boot.
- **Sync callbacks**: thread-safe repaint via `call_from_thread` for remote changes, status changes, and conflict toasts.
- **Data refresh** (`refresh_data`): reloads tasks/completions/streak/month-stats/journal-markers/sparkline and computes target progress.
- **Animation orchestrators**: `animate_progress_bar`, `animate_flip`, `animate_month_slide`.
- **Date shifts**: `_shift_date` (move the viewed "current" day) and `_move_cal` (calendar-browsing focus only).
- **Key handling** (`on_key`): full keyboard dispatch (see §7).
- **Actions**: open journal, force sync, add/rename/delete task, cycle theme.
- **CLI** (`main()`): argparse with `--theme {lifeos,phosphor,amber}` and `--db PATH`.

### 3.2 Entry Points
| Entry | What it does |
|-------|--------------|
| `python -m lifeos` | calls `lifeos/app.py:main()` |
| `python daily.py` | backwards-compat proxy: auto-reexecs inside `.venv` if deps missing, then calls `main()` |
| `lifeos.__init__` | exposes `DailyOS`, `DatabaseManager`, `Task`, `Completion`, `JournalEntry`, `SyncState`, `SyncStateEnum` |

---

## 4. Core Data Models (`lifeos/core/models.py`)

All domain types are `@dataclass`es with UUID + ISO-8601 timestamp helpers.

| Model | Fields | Purpose |
|-------|--------|---------|
| `Task` | `id` (int, SQLite PK), `title`, `sort_order`, `created_at`, `updated_at`, `uuid`, `active` | A daily ritual/habit |
| `Completion` | `task_id`, `date`, `done`, `id?`, `uuid`, `task_uuid`, `completed_at`, `updated_at` | A per-day check-off state |
| `JournalEntry` | `date`, `content`, `word_count`, `id?`, `uuid`, `created_at`, `updated_at`, `mtime` | A single day's journal |
| `SyncState` | `status` (`SyncStateEnum`), `last_synced_at?`, `message`, `unpushed_count` | Live sync status |
| `SyncStateEnum` | `LIVE`, `SYNCING`, `OFFLINE`, `CONFLICT`, `LOCAL_ONLY` | Sync status enum |

Helpers: `generate_uuid()` (UUIDv4) and `current_iso_time()` (UTC ISO-8601).

`JournalEntry.calculate_word_count()` returns `len(content.split())`.

---

## 5. Local Persistence (`lifeos/db/local.py` — `DatabaseManager`)

Storage location (default): `~/.lifeos/daily.db` (SQLite) and `~/.lifeos/journal/` (plain text mirrors), with `~/.lifeos/journal/conflicts/` for conflict archives.

### 5.1 SQLite Schema (5 tables)
1. **`tasks`** — `id`, `title`, `sort_order`, `created_at`, `uuid`, `updated_at`, `dirty`, `deleted`, `active`
2. **`completions`** — `task_id`, `date`, `done`, `uuid`, `task_uuid`, `completed_at`, `updated_at`, `dirty`, `deleted` (composite PK `(task_id, date)`, FK cascade)
3. **`journal_entries`** — `id`, `uuid UNIQUE`, `date UNIQUE`, `content`, `word_count`, `created_at`, `updated_at`, `dirty`, `deleted`
4. **`sync_outbox`** — `id`, `table_name`, `record_uuid`, `action`, `payload` (JSON), `created_at`, `attempts`, `last_error`
5. **`sync_meta`** — `key`, `value` (e.g. `last_sync_timestamp` cursor)

### 5.2 Schema Migrations
`_migrate_existing_schema()` is **additive-only**: uses `PRAGMA table_info` to detect missing columns (`uuid`, `updated_at`, `dirty`, `deleted`, `active`, `task_uuid`, `completed_at`) and `ALTER TABLE … ADD COLUMN` them. It also **backfills** missing UUIDs and timestamps for legacy rows. No destructive migrations.

### 5.3 Auto-Seeding
On first run (when `tasks` is empty), 5 default routines are inserted and enqueued to the outbox:
1. Morning sunlight + Hydration (500ml)
2. Deep focus session (90 mins)
3. Zone 2 Cardio or Strength workout
4. Read 15 pages of non-fiction
5. Nightly retrospective & tomorrow plan

### 5.4 Task Operations
- `get_tasks()` → ordered `List[Task]` (active, not deleted)
- `add_task(title)` → assigns max+1 `sort_order`, UUID, enqueues `UPSERT`
- `update_task_title(id, title)` → marks `dirty`, enqueues `UPSERT`
- `delete_task(id)` → **soft delete** (`deleted=1`), hard-deletes its completions, re-normalizes remaining `sort_order`s, enqueues `DELETE`
- `reorder_task(id, direction)` → swaps with neighbor, rewrites `sort_order`s, enqueues `UPSERT` per moved row

### 5.5 Completions
- `get_day_completions(date)` → `Dict[task_id, Completion]`
- `toggle_completion(task_id, date)` → inserts or flips state, tracks `completed_at`/`updated_at`, marks `dirty`, enqueues `UPSERT`

### 5.6 Analytics
- `calculate_streak(as_of_date)` → consecutive days (incl. today if complete) where **all** active tasks are done
- `get_month_completion_stats(year, month)` → `{date: (done_count, total)}` for every day in month
- `get_past_7_days_fractions(current_date)` → 7 fraction values for the sparkline

### 5.7 Journal — Dual-Mirrored Plain Text + SQLite + Outbox
The journal is the "precious data" subsystem:
- `get_journal_file_path(date)` → `~/.lifeos/journal/YYYY-MM-DD.txt`
- `get_journal_entry(date)`:
  - Reads both the DB row **and** the `.txt` file.
  - If the file was edited externally (content differs from DB), it **reconciles** DB ← file and enqueues an outbox sync.
  - If the file is missing but DB has content, it **re-writes the mirror file**.
  - If only the file exists, it **imports** it into the DB.
- `save_journal_entry(date, content, expected_mtime?)`:
  - Detects **external edit collisions** via mtime drift (`> 0.001s`).
  - Writes the `.txt` file, updates/inserts SQLite, enqueues `UPSERT`.
  - Returns `(JournalEntry, is_collision)`.
- `delete_journal_entry(date)` → removes `.txt` + soft-deletes DB row + enqueues `DELETE`
- `list_journal_entries()` → non-empty, non-deleted entries, newest first
- `get_dates_with_journals(start, end)` → set of dates with non-empty journal (drives calendar markers)

**Guarantee**: journal content is never silently overwritten — reconciliation is bidirectional and outbox-recorded.

---

## 6. Cloud Sync (`lifeos/db/supabase_sync.py` — `SupabaseSyncEngine`)

### 6.1 Credentials Resolution
Loads `.env` from CWD, then `~/.lifeos/.env`, then the environment. Key preference order:
`SUPABASE_SERVICE_ROLE_KEY` → `SUPABASE_ANON_KEY` → `SUPABASE_PUBLISHABLE_KEY`.

If both URL and key exist → `create_client()` → status `LIVE`. Otherwise `LOCAL_ONLY`. A client construction failure → `OFFLINE`.

### 6.2 Worker Loop (daemon thread `lifeos-sync-worker`)
- Initial `_reconcile()` if client is ready.
- Loop: waits on a trigger event (5s timeout), clears it, then:
  - If no client, retries credential reload; otherwise sleeps and continues.
  - `_push_outbox()`, then `_pull_inbound()` (on trigger or every 25s).
  - On success: `last_synced_at` = time, status `LIVE`.
  - On exception: **exponential backoff** `min(60, 2**min(errors,6))` seconds, status `OFFLINE · retry in Ns`.

### 6.3 Outbound Push (`_push_outbox`)
- Selects up to 50 outbox rows ordered by table priority: `routine_tasks` → `journal_entries` → `completions` → other, then by id.
- `UPSERT` or `DELETE` against the Supabase table.
- On success: removes outbox row + clears `dirty` flag on the local row.
- On failure: increments `attempts`, stores `last_error`, re-raises to trigger backoff (mutation **never dropped**).

### 6.4 Inbound Pull (`_pull_inbound`)
- Pulls `routine_tasks`, `completions`, `journal_entries` where `updated_at > last_sync_timestamp`.
- Advances the cursor via `sync_meta`.
- Notifies `on_remote_change` → UI repaints.

### 6.5 Inbound Appliers (conflict resolution)
- **Tasks** (`_apply_remote_task`): insert new remote task; else if local `dirty` **and** local `updated_at` is newer → local wins; else apply remote.
- **Completions** (`_apply_remote_completion`): maps remote `task_uuid` → local `task_id`; same LWW logic.
- **Journals** (`_apply_remote_journal`): the **precious-data rule**:
  - New remote entry → insert + write mirror `.txt`.
  - Identical content → just clear `dirty`.
  - Different content + local dirty → **genuine conflict**:
    - newer `updated_at` wins (canonical in DB + `.txt`),
    - loser archived to `~/.lifeos/journal/conflicts/YYYY-MM-DD-HHMMSS.txt`,
    - `on_conflict(date, backup_path)` fired → UI toast.

### 6.6 Status → UI
`_update_status` calls `on_status_change(state)` → `DailyOS._on_sync_status_event` → thread-safe `HeaderBar.refresh()`.

---

## 7. UI / Widgets (`lifeos/ui/widgets.py`)

All widgets read live state from `self.app` (the `DailyOS`), so repaints are cheap and consistent. No widget hardcodes colors — everything funnels through the theme.

| Widget | Purpose |
|--------|---------|
| `HeaderBar` | Logo mark · wordmark · viewed date + `TODAY`/`PAST`/`FUTURE` tag · sync badge (`☁ live`, `↻ syncing`, `⊘ offline/local`, `⚠ conflict`) · streak flame `♦Nd` · live clock `HH:MM:SS` |
| `HeroBanner` | Contextual motivational headline based on past/present/future + progress (e.g. "Win the morning.", "Day complete — banked.") |
| `TaskListView` | Ritual list with cursor, checkbox glyphs, selection band, flip animation, numbered rows |
| `MonthCalendarView` | Fixed-width 21-char month grid with completion semaphores (● done / ◐ partial / journal ▪) and date highlighting (focus/current/today) |
| `MomentumDock` | `N/M complete` + 7-day sparkline + smoothed progress bar + momentum micro-copy |
| `ToastRail` | Ephemeral feedback line |
| `KeyChipBar` | Context-sensitive keyboard shortcut chips (changes per mode) |
| `BootOverlay` | Skippable animated boot splash with stage checklist |
| `TextInputModal` | Add/Rename input modal (`ModalScreen[Optional[str]]`) |
| `ConfirmModal` | Y/N destructive confirmation modal (`ModalScreen[bool]`) |

---

## 8. Journal Screen (`lifeos/ui/journal_screen.py` — `JournalScreen`)

A full `Screen` pushed on top of the main app. Three modes:

| Mode | Trigger | Behavior |
|------|---------|----------|
| **read** | default | Renders `JournalReaderView` (plain text, or empty-state hint) |
| **edit** | `E` / `Enter` | `TextArea` with **debounced autosave (~800ms)**; `Esc` or `Ctrl+S` flushes and returns to read |
| **browse** | `B` | `JournalBrowseView` — chronological index (date, word count, first-line preview); `↑/↓` + `Enter` open an entry |

Details:
- `JournalHeader` shows date, `TODAY`/`PAST`/`FUTURE`, mode, word count, save status, and a **midnight rollover** warning if the entry was opened on a different day.
- `_flush_save`: empty content → `delete_journal_entry`; otherwise `save_journal_entry` with mtime collision guard; notifies sync engine + refreshes calendar markers.
- Arrow keys are **blocked** in journal read mode to prevent accidental date switching.
- `D`/`X` deletes the day's entry (with `ConfirmModal`).

---

## 9. Theme Engine (`lifeos/ui/themes.py`)

A single source of truth for all visual tokens. No hardcoded colors anywhere in widgets.

### 9.1 Capability Detection
- `detect_color_level()` → `truecolor` | `eight_bit` | `standard` (based on `NO_COLOR`, `TERM`, `COLORTERM`, `256color`)
- `detect_unicode()` → UTF-8 locale detection
- `Capabilities.reduced_motion` → honors `LIFEOS_NO_MOTION`, `NO_MOTION`, `REDUCE_MOTION`

### 9.2 Three Themes (each with truecolor / 256 / 16 palettes)
| Theme | Character |
|-------|-----------|
| `lifeos` | cyan-on-dark flagship |
| `phosphor` | monochrome matrix green |
| `amber` | warm single-hue amber |

### 9.3 Glyphs
Full Unicode set with per-glyph **ASCII fallback** (e.g. `✓`→`x`, `█`→`#`, `●`→`o`, `☁`→`~`). Driven by `build_glyphs(unicode)`.

### 9.4 Design Tokens
- `Palette` (19 semantic color slots), `TypeRamp`, `Spacing`, `Metrics`, `AnimTuning`, `Messages` (micro-copy registry), `BOOT_STAGES`.
- Generated Textual **CSS template** (`_build_css`) with `$token` variables substituted from the palette (Rich→CSS color translation via `css_color()`).

### 9.5 Animation Utilities
- `ease_out_cubic`, `ease_out_back`
- `progress_bar_cells()` — eighth-cell ("braille-smooth") horizontal bar
- `sparkline()`, `dotgrid()`, `fit()`, `dim_style()`
- `Animator` — single-timer, named-sequence, generation-guarded frame driver (`play`, `cancel`, `_tick`)

---

## 10. Keyboard Map (from `DailyOS.on_key` + `JournalScreen.on_key`)

### Main list mode
| Key | Action |
|-----|--------|
| `↑`/`k` | move cursor up |
| `↓`/`j` | move cursor down |
| `Space`/`Enter` | toggle completion |
| `A` | add ritual |
| `E`/`R` | rename ritual |
| `D`/`X` | delete ritual |
| `Shift+K`/`Ctrl+↑`/`Alt+↑`/`[`/`K` | move up |
| `Shift+J`/`Ctrl+↓`/`Alt+↓`/`]`/`J` | move down |
| `←`/`h` | previous day |
| `→`/`l` | next day |
| `0`/`today` | jump to today |
| `C` | toggle calendar browse |
| `J`/`5` | open journal |
| `S` | force sync |
| `T` | cycle theme |
| `Q` | quit |

### Calendar browse mode (`calendar_active`)
| Key | Action |
|-----|--------|
| `←`/`h`, `→`/`l` | ±1 day |
| `↑`/`k`, `↓`/`j` | ±1 week |
| `Space`/`Enter` | jump to focused date |
| `0`/`today` | back to today |
| `Esc`/`C` | exit browse |
| `J`, `S`, `T`, `Q` | journal / sync / theme / quit |

### Journal screen
| Mode | Key | Action |
|------|-----|--------|
| read | `E`/`Enter` | edit |
| read | `B` | browse |
| read | `D`/`X` | delete (confirm) |
| read | `S` / `T` | sync / theme |
| read | `Esc`/`J`/`Q` | back to habits |
| read | `←`/`→`/`h`/`l`/`0`/`today` | **blocked** (no date switch) |
| edit | `Esc`/`Ctrl+S` | save & exit |
| browse | `↑`/`↓` | select |
| browse | `Enter`/`Space` | open entry |
| browse | `Esc`/`B` | back to read |

---

## 11. Cloud Schema (`supabase/schema.sql`)

Three tables, RLS enabled, Realtime publication registered:

| Table | Columns (key) | Notes |
|-------|---------------|-------|
| `routine_tasks` | `id UUID PK`, `user_id`, `title`, `position`, `active`, `created_at`, `updated_at` | |
| `completions` | `id UUID PK`, `user_id`, `task_id FK`, `date`, `done`, `completed_at`, `updated_at` | unique `(user_id, task_id, date)` |
| `journal_entries` | `id UUID PK`, `user_id`, `date`, `content`, `word_count`, `created_at`, `updated_at` | unique `(user_id, date)` |

- Indexes on `(user_id, position)`, `(user_id, date)`, `(task_id, date)`.
- RLS policies for `authenticated` (own rows) **and** `anon` (single-user open access).
- `supabase_realtime` publication for all three tables.

---

## 12. Tests & Verification

### 12.1 pytest suite (17 tests, all passing)
`tests/test_lifeos.py` (13 tests):
- **Phase 1** — models + DB init/seeding
- **Phase 2** — journal: plain-text no-metadata, dual mirror, empty deletion, unicode/emoji roundtrip, 100KB+ performance (<200ms save / <100ms read), external edit detection, future-date journals, browse + calendar markers
- **Phase 3** — sync: offline zero-crash + outbox capture, conflict preservation creates backup
- **Phase 4** — progress bar cells (unicode + ASCII), continuous streak

`tests/test_ui_flow.py` (3 async Textual-harness tests, + 1 = 4 total):
- boot overlay dismiss on key
- app screen flow + journal navigation (toggle, open journal, edit, save, return)
- journal arrow keys do not switch dates

> Command: `.venv/bin/python -m pytest -q` → **17 passed, 8 warnings**.

### 12.2 Legacy self-test (`test_daily.py`)
Standalone script (not part of pytest) with 9 assertions covering auto-seed, add, rename, reorder, isolated per-day toggle, streak=2, cascading delete, month stats, headless app init. Uses legacy `from daily import …` imports.

---

## 13. Dependencies

From `pyproject.toml` (`requires-python >= 3.8`):
- `textual>=0.82.0`
- `rich>=13.0.0`
- `supabase>=2.0.0`
- `python-dotenv>=1.0.0`

`requirements.txt` additionally pins (dev/tooling): `pytest>=8.0.0`, `codegraph>=1.2.0`, `websockets>=13.0.0`, `requests>=2.31.0`.

---

## 14. Configuration & Environment

- **Theme persistence**: `~/.lifeos/theme.cfg` (single line: theme name). Env override: `LIFEOS_THEME`.
- **Env vars**: `LIFEOS_NO_MOTION`, `NO_MOTION`, `REDUCE_MOTION` (disable animations); `LIFEOS_AMBIENT` (enable flame flicker); `NO_COLOR`.
- **CLI flags**: `--theme {lifeos,phosphor,amber}`, `--db PATH`.
- **`.env`** (gitignored, present locally) holds Supabase credentials: URL, anon key, publishable key, service role key, secret key, and a Postgres connection string. ⚠ These are real secrets — see §18.

---

## 15. What Works (Implemented & Verified)

✅ Full habit CRUD (add, rename, delete, reorder) with soft-delete + sort normalization
✅ Per-day isolated completion toggling
✅ Streak calculation (all-tasks-complete rule, continuous backwards)
✅ Monthly completion stats + 7-day sparkline
✅ Fixed-width, non-wrapping calendar with completion semaphores + journal markers
✅ Interactive calendar browse mode (day/week navigation, jump, today)
✅ Dual-mirrored journal (SQLite + plain `.txt`) with external-edit reconciliation
✅ Debounced (~800ms) autosave editor with mtime collision guards
✅ Chronological journal browse + midnight rollover indicator
✅ Local-first offline outbox queue with exponential backoff retry
✅ Bidirectional Supabase sync (push UPSERT/DELETE + incremental pull)
✅ LWW conflict resolution for tasks/completions; non-destructive conflict backup for journals
✅ Live sync status badges in header
✅ 3 themes × 3 color-depth palettes + unicode/ASCII glyph fallback
✅ Reduced-motion accessibility mode
✅ Animated boot (skippable), eased progress bar, flip animation, month slide
✅ Responsive stacked layout below width threshold
✅ Theme cycling (live CSS swap) + persistence
✅ 17 automated tests passing

---

## 16. What Is NOT Yet Implemented / Gaps / Caveats

1. **Realtime subscriptions are not consumed.** `schema.sql` registers tables in `supabase_realtime`, and `SupabaseSyncEngine` has a `_realtime_channel` attribute, but it is **never set up**. Sync is polling-driven (25s interval + trigger events), not push/realtime.
2. **`TasksScreen` (`tasks_screen.py`) is dead code.** The app composes widgets directly; `TasksScreen` duplicates the key handler but is never instantiated.
3. **`lifeos_theme.py` (800 lines) is a stale standalone copy** of the theme engine with **older content** (no `cloud_*` glyphs, no journal glyphs/`Messages` entries). It is not imported by anything. Risk of drift.
4. **`daily.py` + `test_daily.py` are legacy shims** for backwards compatibility, separate from the pytest suite. Two test paths exist.
5. **No user authentication flow.** Sync uses service-role/anon keys; there is no login/user-scoping in the client (RLS policies exist server-side, but the client does not set `user_id`).
6. **`.env` contains live secrets** on disk (gitignored, but present). See §18.
7. **No README** at repo root (only `SYNC.md`). `pyproject.toml` declares `readme = "README.md"` but the file does not exist (packaging would warn/fail on build).
8. **`call_from_thread` runtime warning** — in `app.py`, the callback is invoked but a `RuntimeWarning: coroutine … never awaited` appears in tests (minor: `call_from_thread` returns an awaitable that isn't awaited in this sync context).
9. **Toast TTL is not enforced.** `AnimTuning.toast_ttl = 2.6` and `Messages` include several `toast_*` strings (`toast_journal_saved`, `toast_sync_done`, `toast_sync_offline`, `toast_conflict`, `toast_future`) that are **never used** — toasts are set but never auto-cleared.
10. **Ambient flame flicker** is opt-in (`LIFEOS_AMBIENT`) and only affects the header flame glyph.
11. **No undo** for destructive actions (delete is confirm-gated, but no rollback).
12. **`capabilities` detects unicode via locale only**; `TERM=dumb` may mis-detect in some terminals (documented tradeoff in the legacy file comment).

---

## 17. File Inventory (line counts)

| File | Lines | Role |
|------|-------|------|
| `lifeos/app.py` | 685 | Master App + controller |
| `lifeos/db/local.py` | 844 | SQLite + journal mirror + outbox |
| `lifeos/db/supabase_sync.py` | 518 | Cloud sync engine |
| `lifeos/ui/themes.py` | 771 | Theme engine |
| `lifeos/ui/widgets.py` | 581 | Reusable widgets |
| `lifeos/ui/journal_screen.py` | 394 | Journal screen |
| `lifeos/ui/tasks_screen.py` | 239 | ⚠ unused legacy screen |
| `lifeos/core/models.py` | 77 | Data models |
| `lifeos/ui/__init__.py` | 37 | UI exports |
| `lifeos/core/__init__.py` | 23 | Core exports |
| `lifeos/__init__.py` | 19 | Package exports |
| `lifeos/__main__.py` | 8 | `-m` entrypoint |
| `lifeos/db/__init__.py` | 7 | DB exports |
| `supabase/schema.sql` | 123 | Cloud schema |
| `tests/test_lifeos.py` | 288 | pytest unit/integration |
| `tests/test_ui_flow.py` | 117 | pytest async UI tests |
| `lifeos_theme.py` | 800 | ⚠ legacy theme copy |
| `test_daily.py` | 104 | legacy self-test |
| `daily.py` | 28 | legacy entrypoint |
| `SYNC.md` | 92 | sync docs |
| `codegraph.html` | — | generated viz artifact |

---

## 18. Security Notes

- `.env` is correctly listed in `.gitignore`, but the file **currently exists on disk with real Supabase keys** (URL, anon, publishable, service-role, secret key, and a Postgres connection string). It is **not committed** to git (working tree clean).
- The app prefers the **service-role key** for Supabase access, which bypasses RLS. Given RLS also permits `anon` open access (single-user mode), this is acceptable for a personal tool but not for multi-user deployment.
- No secrets are logged by the code (outbox `last_error` stores exception strings — verify these don't leak keys in practice; currently they only capture Supabase client error text).

---

## 19. Git History

```
e09142a feat: complete lifeOS refactor, dual-mirrored journal, Supabase cloud sync & UI polish
7b7b168 feat: persist theme, fix Shift+K/J reordering, and add full interactive calendar mode
76c9db0 feat: implement state-of-the-art lifeOS Daily TUI with themes, animations, and typography
c209caa initialization
```
Branch `main` is up-to-date with `origin/main`; working tree clean.

---

## 20. Quick Reference — How To Run

```bash
# using the venv
.venv/bin/python -m lifeos                # run the app
.venv/bin/python -m lifeos --theme amber  # with a theme
.venv/bin/python -m lifeos --db /path/to/db.db

# or the legacy proxy
python daily.py

# tests
.venv/bin/python -m pytest -q

# regenerate dependency graph
.venv/bin/codegraph lifeos
```
