"""
lifeOS Supabase Sync Engine
===========================
Local-first, offline-tolerant bidirectional synchronization with Realtime subscriptions,
exponential backoff, outbox replay, and conflict-safe journal preservation.
"""

from __future__ import annotations

import datetime
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import dotenv

from lifeos.core.models import (
    Completion,
    JournalEntry,
    SyncState,
    SyncStateEnum,
    Task,
    current_iso_time,
    generate_uuid,
)


class SupabaseSyncEngine:
    """Background synchronization engine connecting SQLite with Supabase."""

    def __init__(
        self,
        db_manager: Any,
        on_remote_change: Optional[Callable[[], None]] = None,
        on_status_change: Optional[Callable[[SyncState], None]] = None,
        on_conflict: Optional[Callable[[str, str], None]] = None,
    ):
        self.db = db_manager
        self.on_remote_change = on_remote_change
        self.on_status_change = on_status_change
        self.on_conflict = on_conflict

        self.state = SyncState(status=SyncStateEnum.LOCAL_ONLY, message="local-only")
        self._stop_event = threading.Event()
        self._trigger_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.url: Optional[str] = None
        self.key: Optional[str] = None
        self.client: Any = None
        self._realtime_channel: Any = None

        self._load_credentials()

    def _load_credentials(self) -> None:
        """Discover credentials from .env, ~/.lifeos/.env, or environment."""
        dotenv.load_dotenv()
        home_env = Path.home() / ".lifeos" / ".env"
        if home_env.exists():
            dotenv.load_dotenv(dotenv_path=home_env)

        self.url = os.getenv("SUPABASE_URL")
        self.key = (
            os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or os.getenv("SUPABASE_ANON_KEY")
            or os.getenv("SUPABASE_PUBLISHABLE_KEY")
        )

        if self.url and self.key:
            try:
                from supabase import create_client
                self.client = create_client(self.url, self.key)
                self._update_status(SyncStateEnum.LIVE, "cloud ready")
            except Exception as e:
                self.client = None
                self._update_status(SyncStateEnum.OFFLINE, f"client error: {e}")
        else:
            self._update_status(SyncStateEnum.LOCAL_ONLY, "local-only")

    def _update_status(
        self,
        status: SyncStateEnum,
        message: str = "",
        unpushed: int = 0,
    ) -> None:
        self.state.status = status
        self.state.message = message
        self.state.unpushed_count = unpushed
        if self.on_status_change:
            try:
                self.on_status_change(self.state)
            except Exception:
                pass

    def start(self) -> None:
        """Start background sync worker thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="lifeos-sync-worker")
        self._thread.start()

    def stop(self) -> None:
        """Stop background worker cleanly."""
        self._stop_event.set()
        self._trigger_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def trigger_sync(self) -> None:
        """Signal worker to perform an immediate sync."""
        self._trigger_event.set()

    def notify_local_mutation(self) -> None:
        """Call whenever local data is modified."""
        self._trigger_event.set()

    # -----------------------------------------------------------------------
    # Worker Loop
    # -----------------------------------------------------------------------

    def _worker_loop(self) -> None:
        last_pull_time = 0.0
        pull_interval = 25.0  # Periodic reconcile
        consecutive_errors = 0

        # Initial reconciliation if client ready
        if self.client:
            self._update_status(SyncStateEnum.SYNCING, "initial sync…")
            self._reconcile()

        while not self._stop_event.is_set():
            try:
                # Wait for trigger or timeout
                self._trigger_event.wait(timeout=5.0)
                self._trigger_event.clear()

                if self._stop_event.is_set():
                    break

                if not self.client:
                    # Retry credential reload in case .env was added
                    self._load_credentials()
                    if not self.client:
                        self._update_status(SyncStateEnum.LOCAL_ONLY, "local-only")
                        time.sleep(5.0)
                        continue

                # Process outbound mutations
                pushed = self._push_outbox()

                now = time.time()
                if (now - last_pull_time) >= pull_interval or pushed > 0:
                    self._pull_inbound()
                    last_pull_time = now

                consecutive_errors = 0
                now_str = datetime.datetime.now().strftime("%H:%M:%S")
                self.state.last_synced_at = now_str
                self._update_status(SyncStateEnum.LIVE, f"synced at {now_str}")

            except Exception as e:
                consecutive_errors += 1
                backoff = min(60, 2 ** min(consecutive_errors, 6))
                self._update_status(
                    SyncStateEnum.OFFLINE,
                    f"offline · retry in {backoff}s",
                )
                time.sleep(backoff)

    # -----------------------------------------------------------------------
    # Outbound Push (Outbox queue processing)
    # -----------------------------------------------------------------------

    def _push_outbox(self) -> int:
        if not self.client:
            return 0

        pushed_count = 0
        with self.db._get_conn() as conn:
            cur = conn.execute(
                """
                SELECT id, table_name, record_uuid, action, payload, attempts
                FROM sync_outbox
                ORDER BY CASE table_name
                    WHEN 'routine_tasks' THEN 1
                    WHEN 'journal_entries' THEN 2
                    WHEN 'completions' THEN 3
                    ELSE 4
                END, id ASC
                LIMIT 50
                """
            )
            rows = cur.fetchall()

        if not rows:
            return 0

        self._update_status(SyncStateEnum.SYNCING, f"pushing {len(rows)} changes…", len(rows))

        for row in rows:
            outbox_id = row["id"]
            table_name = row["table_name"]
            action = row["action"]
            payload = json.loads(row["payload"])

            try:
                if action == "UPSERT":
                    self.client.table(table_name).upsert(payload).execute()
                elif action == "DELETE":
                    self.client.table(table_name).delete().eq("id", payload["id"]).execute()

                # Mark pushed: remove from outbox and clear dirty flag in local DB
                with self.db._get_conn() as conn:
                    conn.execute("DELETE FROM sync_outbox WHERE id = ?", (outbox_id,))
                    if table_name == "routine_tasks":
                        conn.execute("UPDATE tasks SET dirty = 0 WHERE uuid = ?", (payload["id"],))
                    elif table_name == "completions":
                        conn.execute("UPDATE completions SET dirty = 0 WHERE uuid = ?", (payload["id"],))
                    elif table_name == "journal_entries":
                        conn.execute("UPDATE journal_entries SET dirty = 0 WHERE uuid = ?", (payload["id"],))
                    conn.commit()

                pushed_count += 1

            except Exception as e:
                # Update attempt count and last error for retry
                with self.db._get_conn() as conn:
                    conn.execute(
                        "UPDATE sync_outbox SET attempts = attempts + 1, last_error = ? WHERE id = ?",
                        (str(e), outbox_id),
                    )
                    conn.commit()
                raise e

        return pushed_count

    # -----------------------------------------------------------------------
    # Inbound Pull & Conflict Resolution
    # -----------------------------------------------------------------------

    def _pull_inbound(self) -> None:
        if not self.client:
            return

        last_sync = self._get_meta("last_sync_timestamp", "1970-01-01T00:00:00Z")
        changed = False

        # 1. Pull routine_tasks
        try:
            res_tasks = (
                self.client.table("routine_tasks")
                .select("*")
                .gt("updated_at", last_sync)
                .execute()
            )
            if res_tasks.data:
                for remote_t in res_tasks.data:
                    if self._apply_remote_task(remote_t):
                        changed = True
        except Exception:
            pass

        # 2. Pull completions
        try:
            res_comps = (
                self.client.table("completions")
                .select("*")
                .gt("updated_at", last_sync)
                .execute()
            )
            if res_comps.data:
                for remote_c in res_comps.data:
                    if self._apply_remote_completion(remote_c):
                        changed = True
        except Exception:
            pass

        # 3. Pull journal_entries
        try:
            res_journals = (
                self.client.table("journal_entries")
                .select("*")
                .gt("updated_at", last_sync)
                .execute()
            )
            if res_journals.data:
                for remote_j in res_journals.data:
                    if self._apply_remote_journal(remote_j):
                        changed = True
        except Exception:
            pass

        self._set_meta("last_sync_timestamp", current_iso_time())

        if changed and self.on_remote_change:
            try:
                self.on_remote_change()
            except Exception:
                pass

    def _reconcile(self) -> None:
        """Initial bidirectional reconciliation on startup."""
        try:
            # First, ensure all local tasks exist on Supabase
            tasks = self.db.get_tasks()
            for t in tasks:
                self.client.table("routine_tasks").upsert({
                    "id": t.uuid,
                    "title": t.title,
                    "position": t.sort_order,
                    "active": t.active,
                    "created_at": t.created_at or current_iso_time(),
                    "updated_at": t.updated_at or current_iso_time(),
                }).execute()

            self._push_outbox()
            self._pull_inbound()
            now_str = datetime.datetime.now().strftime("%H:%M:%S")
            self._update_status(SyncStateEnum.LIVE, f"synced at {now_str}")
        except Exception as e:
            self._update_status(SyncStateEnum.OFFLINE, f"initial sync failed: {e}")

    # -----------------------------------------------------------------------
    # Inbound Appliers with LWW and Conflict Backups
    # -----------------------------------------------------------------------

    def _apply_remote_task(self, remote_t: Dict[str, Any]) -> bool:
        t_uuid = remote_t["id"]
        title = remote_t.get("title", "")
        pos = remote_t.get("position", 0)
        active = remote_t.get("active", True)
        u_at = remote_t.get("updated_at", "")
        c_at = remote_t.get("created_at", "")

        with self.db._get_conn() as conn:
            cur = conn.execute("SELECT id, title, sort_order, updated_at, dirty FROM tasks WHERE uuid = ?", (t_uuid,))
            local_row = cur.fetchone()

            if local_row is None:
                # Insert new remote task locally
                conn.execute(
                    """
                    INSERT INTO tasks (title, sort_order, uuid, created_at, updated_at, dirty, deleted, active)
                    VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (title, pos, t_uuid, c_at, u_at, 0 if active else 1, 1 if active else 0),
                )
                conn.commit()
                return True
            else:
                # If local row is dirty and newer, let local win
                local_u_at = local_row["updated_at"] or ""
                if local_row["dirty"] and local_u_at > u_at:
                    return False
                # Apply remote
                conn.execute(
                    """
                    UPDATE tasks
                    SET title = ?, sort_order = ?, updated_at = ?, deleted = ?, active = ?, dirty = 0
                    WHERE uuid = ?
                    """,
                    (title, pos, u_at, 0 if active else 1, 1 if active else 0, t_uuid),
                )
                conn.commit()
                return True

    def _apply_remote_completion(self, remote_c: Dict[str, Any]) -> bool:
        c_uuid = remote_c["id"]
        t_uuid = remote_c.get("task_id", "")
        date_str = str(remote_c.get("date", ""))
        done = bool(remote_c.get("done", True))
        c_at = remote_c.get("completed_at", "")
        u_at = remote_c.get("updated_at", "")

        with self.db._get_conn() as conn:
            # Find local task id
            t_cur = conn.execute("SELECT id FROM tasks WHERE uuid = ?", (t_uuid,))
            t_row = t_cur.fetchone()
            if not t_row:
                return False
            task_id = t_row["id"]

            cur = conn.execute(
                "SELECT uuid, done, updated_at, dirty FROM completions WHERE task_id = ? AND date = ?",
                (task_id, date_str),
            )
            local_row = cur.fetchone()

            if local_row is None:
                conn.execute(
                    """
                    INSERT INTO completions (task_id, date, done, uuid, task_uuid, completed_at, updated_at, dirty)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (task_id, date_str, 1 if done else 0, c_uuid, t_uuid, c_at, u_at),
                )
                conn.commit()
                return True
            else:
                local_u_at = local_row["updated_at"] or ""
                if local_row["dirty"] and local_u_at > u_at:
                    return False
                conn.execute(
                    """
                    UPDATE completions
                    SET done = ?, uuid = ?, completed_at = ?, updated_at = ?, dirty = 0
                    WHERE task_id = ? AND date = ?
                    """,
                    (1 if done else 0, c_uuid, c_at, u_at, task_id, date_str),
                )
                conn.commit()
                return True

    def _apply_remote_journal(self, remote_j: Dict[str, Any]) -> bool:
        j_uuid = remote_j["id"]
        date_str = str(remote_j.get("date", ""))
        remote_content = remote_j.get("content", "")
        remote_w_count = remote_j.get("word_count", 0)
        remote_u_at = remote_j.get("updated_at", "")
        remote_c_at = remote_j.get("created_at", "")

        with self.db._get_conn() as conn:
            cur = conn.execute(
                "SELECT id, uuid, content, updated_at, dirty FROM journal_entries WHERE date = ?",
                (date_str,),
            )
            local_row = cur.fetchone()

            if local_row is None:
                # New entry from remote: save to DB and write mirror txt file
                conn.execute(
                    """
                    INSERT INTO journal_entries (uuid, date, content, word_count, created_at, updated_at, dirty, deleted)
                    VALUES (?, ?, ?, ?, ?, ?, 0, 0)
                    """,
                    (j_uuid, date_str, remote_content, remote_w_count, remote_c_at, remote_u_at),
                )
                conn.commit()

                # Mirror to plain text file
                file_path = self.db.get_journal_file_path(date_str)
                file_path.write_text(remote_content, encoding="utf-8")
                return True

            local_content = local_row["content"]
            local_u_at = local_row["updated_at"] or ""
            local_dirty = bool(local_row["dirty"])

            if local_content == remote_content:
                conn.execute("UPDATE journal_entries SET dirty = 0 WHERE date = ?", (date_str,))
                conn.commit()
                return False

            # Genuine conflict: both modified and different
            if local_dirty:
                # Backup loser to conflicts directory
                ts = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
                conflict_file = self.db.conflicts_dir / f"{date_str}-{ts}.txt"

                if local_u_at > remote_u_at:
                    # Local wins, remote is saved as loser backup
                    conflict_file.write_text(remote_content, encoding="utf-8")
                    if self.on_conflict:
                        self.on_conflict(date_str, str(conflict_file))
                    return False
                else:
                    # Remote wins, local is saved as loser backup
                    conflict_file.write_text(local_content, encoding="utf-8")
                    conn.execute(
                        """
                        UPDATE journal_entries
                        SET content = ?, word_count = ?, updated_at = ?, dirty = 0
                        WHERE date = ?
                        """,
                        (remote_content, remote_w_count, remote_u_at, date_str),
                    )
                    conn.commit()
                    file_path = self.db.get_journal_file_path(date_str)
                    file_path.write_text(remote_content, encoding="utf-8")
                    if self.on_conflict:
                        self.on_conflict(date_str, str(conflict_file))
                    return True
            else:
                # Clean remote apply
                conn.execute(
                    """
                    UPDATE journal_entries
                    SET content = ?, word_count = ?, updated_at = ?, dirty = 0
                    WHERE date = ?
                    """,
                    (remote_content, remote_w_count, remote_u_at, date_str),
                )
                conn.commit()
                file_path = self.db.get_journal_file_path(date_str)
                file_path.write_text(remote_content, encoding="utf-8")
                return True

    # -----------------------------------------------------------------------
    # Metadata Helper
    # -----------------------------------------------------------------------

    def _get_meta(self, key: str, default: str = "") -> str:
        with self.db._get_conn() as conn:
            cur = conn.execute("SELECT value FROM sync_meta WHERE key = ?", (key,))
            row = cur.fetchone()
            return row["value"] if row else default

    def _set_meta(self, key: str, value: str) -> None:
        with self.db._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sync_meta (key, value) VALUES (?, ?)",
                (key, value),
            )
            conn.commit()
