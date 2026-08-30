# lifeOS Supabase Sync Architecture & Engine (SYNC.md)

`lifeos` uses a **Local-First, Offline-Tolerant** bidirectional synchronization architecture. The local SQLite database (`~/.lifeos/daily.db`) and human-readable plain text journal files (`~/.lifeos/journal/YYYY-MM-DD.txt`) are the runtime sources of truth. The application remains 100% interactive and zero-latency with or without network connectivity.

---

## 1. Sync State & Data Flow Diagram (ASCII)

```text
               +---------------------------------------------------+
               |             User Actions in lifeOS TUI            |
               | (Check-off, Add Habit, Rename, Reorder, Journal) |
               +---------------------------------------------------+
                                         |
                                         v
                         +-------------------------------+
                         |   Immediate Local Apply       |
                         | - SQLite DB updated           |
                         | - Plain .txt Journal saved    |
                         | - Mutation enqueued in Outbox |
                         +-------------------------------+
                                         |
                                         v
+---------------------------------------------------------------------------------+
|                    SupabaseSyncEngine (Background Daemon Thread)                |
|                                                                                 |
|         +-------------------------------------------------------------+         |
|         |                   OUTBOUND PUSH PIPELINE                    |         |
|         | 1. Read unpushed items from `sync_outbox` table             |         |
|         | 2. Push UPSERT / DELETE to Supabase via REST                |         |
|         | 3. On success: DELETE from outbox & clear `dirty` in SQLite |         |
|         | 4. On network failure: backoff exponential retry (2s..60s)  |         |
|         +-------------------------------------------------------------+         |
|                                         |                                       |
|                                         v                                       |
|         +-------------------------------------------------------------+         |
|         |                   INBOUND PULL PIPELINE                     |         |
|         | 1. Query remote tables for `updated_at > last_sync`         |         |
|         | 2. Reconcile routine_tasks & completions (LWW)              |         |
|         | 3. Journal Conflict Check:                                  |         |
|         |    - If genuine conflict (both modified since last sync):   |         |
|         |      a. Newer timestamp becomes canonical local file/DB     |         |
|         |      b. Loser backed up to ~/.lifeos/journal/conflicts/     |         |
|         |      c. Notify UI via toast (NEVER SILENTLY DISCARD TEXT)   |         |
|         +-------------------------------------------------------------+         |
+---------------------------------------------------------------------------------+
                                    |         ^
                HTTPS REST / Events |         | Realtime / Polling
                                    v         |
               +---------------------------------------------------+
               |             Supabase Cloud Backend                |
               | - routine_tasks (RLS enabled)                     |
               | - completions (RLS enabled)                       |
               | - journal_entries (RLS enabled)                   |
               | - supabase_realtime publication                   |
               +---------------------------------------------------+
```

---

## 2. Outbound Synchronization (Local -> Cloud)
- Every local mutation (habit toggle, creation, reordering, journal autosave) is committed to SQLite instantly.
- The mutation is recorded into `sync_outbox` with its table name, UUID, action (`UPSERT` / `DELETE`), and payload.
- The background thread pushes queued outbox items to Supabase in FIFO order.
- Failed pushes do not block the UI or drop mutations: they survive application restarts and retry automatically with exponential backoff.

---

## 3. Inbound Synchronization (Cloud -> Local)
- Supabase changes (from other devices or Supabase Dashboard) are pulled incrementally by timestamp cursor (`last_sync_timestamp`).
- Changes are applied to the local SQLite database and plain text mirror files.
- The UI is notified via `app.call_from_thread()` to repaint tasks, streak counts, and calendar markers in real time.

---

## 4. Conflict Resolution Rules
1. **Routine Habits & Completions**: Last-Write-Wins (LWW) based on `updated_at` timestamps.
2. **Journal Entries (Precious Data Rule)**:
   - If both local and cloud were modified since last sync with different contents:
     - **Canonical copy**: The version with the more recent `updated_at` timestamp is written to SQLite and `~/.lifeos/journal/YYYY-MM-DD.txt`.
     - **Loser copy**: Automatically saved as `~/.lifeos/journal/conflicts/YYYY-MM-DD-HHMMSS.txt`.
     - **Notification**: A non-intrusive toast is displayed notifying the user of the saved backup.
   - **Zero Data Loss Guarantee**: Journal content is never overwritten without archiving the loser.

---

## 5. UI Status Indicators
- `☁ live` (Green): Cloud sync connected and active.
- `↻ syncing…` (Amber): Outbound changes pushing or inbound reconciles in flight.
- `⊘ offline` / `⊘ local` (Dim): Running locally with offline tolerance.
- `⚠ conflict` (Magenta): Conflict detected and archived safely.
- Press **[S]** at any time in the app to trigger an immediate cloud reconcile.
