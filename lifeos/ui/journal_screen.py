"""
lifeOS Journal Screen
=====================
One living document per calendar day.
Dual-mirrored: plain .txt files at ~/.lifeos/journal/YYYY-MM-DD.txt + SQLite/Supabase.
Features: Reader view, multiline debounced autosave editor, chronological browse list,
external mtime collision guards, and midnight rollover indicators.
"""

from __future__ import annotations

import datetime
from typing import List, Optional

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Label, Static, TextArea

from lifeos.core.models import JournalEntry
from lifeos.ui.themes import Theme, fit
from lifeos.ui.widgets import ConfirmModal, HeaderBar, KeyChipBar, ToastRail


class JournalHeader(Static):
    """Contextual journal metadata: Date, Word count, Status, Mode."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs

        view_date = app.current_date
        today = datetime.date.today()
        is_today = view_date == today
        date_str = view_date.strftime("%A, %B %d, %Y")
        tag = "TODAY" if is_today else ("PAST" if view_date < today else "FUTURE")
        tag_color = p.state_ok if is_today else (p.text_dim if view_date < today else p.state_warn)

        screen: JournalScreen = app.screen
        mode = screen.mode.upper()
        mode_style = f"bold {p.accent_hi}" if mode == "EDIT" else f"{p.text_dim}"

        w_count = screen.current_word_count
        status_msg = screen.save_status

        t = Text()
        t.append(f"{g.journal} JOURNAL ", style=f"bold {p.accent}")
        t.append(f"{g.line_v} ", style=f"{p.line}")
        t.append(date_str, style=f"bold {p.text_hi}")
        t.append(f" [{tag}] ", style=f"bold {tag_color}")
        t.append(f"{g.line_v} ", style=f"{p.line}")
        t.append(f"[{mode}]", style=mode_style)

        # Midnight rollover warning
        if screen.opened_today and datetime.date.today() != screen.opened_today:
            t.append(f"  (opened on {screen.opened_today.strftime('%b %d')})", style=f"bold {p.state_warn}")

        right = Text()
        right.append(f"{w_count} words", style=f"bold {p.text_hi}")
        right.append(f"  {g.line_v}  ", style=f"{p.line}")
        right.append(status_msg, style=f"{p.text_dim}")

        w = self.size.width if self.size.width > 20 else 80
        pad = max(1, w - len(t.plain) - len(right.plain) - 2)
        t.append(" " * pad)
        t.append_text(right)
        return t


class JournalReaderView(Static):
    """Clean reading surface with smooth typography."""
    can_focus = True

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs
        m = th.messages

        screen: JournalScreen = app.screen
        content = screen.current_content

        t = Text()
        if not content or not content.strip():
            t.append("\n\n")
            t.append(f"  {g.journal} Nothing written for this day yet.\n\n", style=f"bold {p.text_hi}")
            t.append(f"  Press ", style=f"{p.text_dim}")
            t.append("[Enter]", style=f"bold {p.accent_hi}")
            t.append(" or ", style=f"{p.text_dim}")
            t.append("[E]", style=f"bold {p.accent_hi}")
            t.append(" to start writing · plain text, mirrors automatically.\n", style=f"{p.text_dim}")
            t.append(f"  Press ", style=f"{p.text_dim}")
            t.append("[B]", style=f"bold {p.accent_hi}")
            t.append(" to browse past entries · ", style=f"{p.text_dim}")
            t.append("[Esc]", style=f"bold {p.accent_hi}")
            t.append(" to return to habits.", style=f"{p.text_dim}")
            return t

        for line in content.splitlines():
            t.append(f"  {line}\n", style=f"{p.text_hi}")
        return t


class JournalBrowseView(Static):
    """Chronological browse list of all journal entries."""
    can_focus = True

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs

        screen: JournalScreen = app.screen
        entries = screen.browse_entries
        cursor = screen.browse_cursor
        w = max(40, self.size.width - 6)

        t = Text()
        t.append(f" {g.journal} Chronological Journal Index ({len(entries)} entries)\n", style=f"bold {p.accent}")
        t.append(f" Use ↑/↓ to navigate · Enter to open · Esc to exit browse\n\n", style=f"{p.text_faint}")

        if not entries:
            t.append(f"  No journal entries recorded yet.\n", style=f"{p.text_dim}")
            return t

        for idx, entry in enumerate(entries):
            is_selected = (idx == cursor)
            prefix = f"{g.w_right} " if is_selected else "  "
            prefix_style = f"bold {p.accent_hi}" if is_selected else f"{p.text_faint}"
            date_style = f"bold {p.accent}" if is_selected else f"bold {p.text_hi}"
            row_bg = f"on {p.band_hot}" if is_selected and p.band_hot and th.caps.colorful else ""

            # Extract first line preview
            first_line = entry.content.strip().splitlines()[0] if entry.content.strip() else "Empty entry"
            preview = fit(first_line, w - 28)

            line = Text()
            line.append(prefix, style=prefix_style)
            line.append(f"{entry.date} ", style=date_style)
            line.append(f"({entry.word_count:3d}w) ", style=f"{p.text_faint}")
            line.append(preview, style=f"bold {p.text_hi}" if is_selected else f"{p.text_dim}")

            plain_len = len(line.plain)
            if plain_len < w:
                line.append(" " * (w - plain_len))
            if row_bg:
                line.stylize(row_bg)

            t.append_text(line)
            t.append("\n")

        return t


class JournalScreen(Screen):
    """Main Journal Screen orchestrating Read, Edit, and Browse modes."""
    AUTO_FOCUS = "#journal_reader"

    def __init__(self):
        super().__init__()
        self.mode: str = "read"  # "read" | "edit" | "browse"
        self.current_content: str = ""
        self.current_word_count: int = 0
        self.current_mtime: float = 0.0
        self.save_status: str = "saved"
        self.opened_today: Optional[datetime.date] = None

        self.browse_entries: List[JournalEntry] = []
        self.browse_cursor: int = 0
        self._autosave_timer: Optional[Any] = None

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="topbar")
        with Vertical(id="journal_container"):
            yield JournalHeader(id="journal_header")
            yield JournalReaderView(id="journal_reader")
            yield TextArea(id="journal_editor")
            yield JournalBrowseView(id="journal_browse_list")
        yield ToastRail(id="toast")
        yield KeyChipBar(id="footer")

    def on_mount(self) -> None:
        self.opened_today = datetime.date.today()
        editor = self.query_one("#journal_editor", TextArea)
        editor.show_line_numbers = False
        editor.display = False
        editor.can_focus = False
        browse = self.query_one("#journal_browse_list", JournalBrowseView)
        browse.display = False

        self.load_current_entry()
        self.set_interval(1.0, self._clock_tick)

    def _clock_tick(self) -> None:
        try:
            self.query_one(HeaderBar).refresh()
            self.query_one(JournalHeader).refresh()
        except Exception:
            pass

    def load_current_entry(self) -> None:
        """Load entry for app.current_date from local SQLite & mirror file."""
        date_str = self.app.current_date.strftime("%Y-%m-%d")
        entry = self.app.db.get_journal_entry(date_str)
        if entry:
            self.current_content = entry.content
            self.current_word_count = entry.word_count
            self.current_mtime = entry.mtime
            self.save_status = "saved"
        else:
            self.current_content = ""
            self.current_word_count = 0
            self.current_mtime = 0.0
            self.save_status = "empty"

        self.mode = "read"
        self._sync_view_visibility()

    def _sync_view_visibility(self) -> None:
        reader = self.query_one("#journal_reader", JournalReaderView)
        editor = self.query_one("#journal_editor", TextArea)
        browse = self.query_one("#journal_browse_list", JournalBrowseView)

        if self.mode == "edit":
            reader.display = False
            browse.display = False
            editor.display = True
            editor.can_focus = True
            editor.text = self.current_content
            editor.focus()
        elif self.mode == "browse":
            reader.display = False
            editor.display = False
            editor.can_focus = False
            browse.display = True
            self.browse_entries = self.app.db.list_journal_entries()
            self.browse_cursor = 0
            browse.refresh()
            browse.focus()
        else:
            editor.display = False
            editor.can_focus = False
            browse.display = False
            reader.display = True
            reader.refresh()
            reader.focus()

        try:
            self.query_one(JournalHeader).refresh()
            self.query_one(KeyChipBar).refresh()
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Autosave & Persistence
    # -----------------------------------------------------------------------

    @on(TextArea.Changed, "#journal_editor")
    def on_text_changed(self, event: TextArea.Changed) -> None:
        if self.mode != "edit":
            return
        self.current_content = event.text_area.text
        self.current_word_count = len(self.current_content.split()) if self.current_content else 0
        self.save_status = "saving…"
        try:
            self.query_one(JournalHeader).refresh()
        except Exception:
            pass

        # Debounced save at ~800ms
        if self._autosave_timer:
            self._autosave_timer.stop()
        self._autosave_timer = self.set_timer(0.8, self._flush_save)

    def _flush_save(self) -> None:
        """Flush text changes to disk & DB."""
        if self.mode == "edit":
            editor = self.query_one("#journal_editor", TextArea)
            self.current_content = editor.text

        date_str = self.app.current_date.strftime("%Y-%m-%d")
        trimmed = self.current_content.strip()

        if not trimmed:
            # If cleared completely, delete entry
            self.app.db.delete_journal_entry(date_str)
            self.current_mtime = 0.0
            self.save_status = "empty"
        else:
            entry, is_col = self.app.db.save_journal_entry(
                date_str,
                self.current_content,
                expected_mtime=self.current_mtime if self.current_mtime > 0 else None,
            )
            self.current_mtime = entry.mtime
            now_t = datetime.datetime.now().strftime("%H:%M:%S")
            self.save_status = f"saved at {now_t}"
            if is_col:
                self.app.set_toast("External change detected: updated locally.")

        self.app.sync_engine.notify_local_mutation()
        self.app.refresh_journal_markers()
        try:
            self.query_one(JournalHeader).refresh()
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Key Navigation & Actions
    # -----------------------------------------------------------------------

    def on_key(self, event: events.Key) -> None:
        k = event.key
        k_lower = k.lower()

        # In Edit Mode:
        if self.mode == "edit":
            if k == "escape" or (event.character == "s" and event.has_control):
                self._flush_save()
                self.mode = "read"
                self._sync_view_visibility()
                self.app.set_toast(f"Journal saved ({self.current_word_count} words)")
                event.stop()
                return
            return  # Allow TextArea to receive typing

        # In Browse Mode:
        if self.mode == "browse":
            if k_lower in ("escape", "b"):
                self.mode = "read"
                self._sync_view_visibility()
                return
            elif k_lower in ("up", "k"):
                if self.browse_entries:
                    self.browse_cursor = max(0, self.browse_cursor - 1)
                    self.query_one("#journal_browse_list", JournalBrowseView).refresh()
                return
            elif k_lower in ("down", "j"):
                if self.browse_entries:
                    self.browse_cursor = min(len(self.browse_entries) - 1, self.browse_cursor + 1)
                    self.query_one("#journal_browse_list", JournalBrowseView).refresh()
                return
            elif k in ("enter", "space"):
                if self.browse_entries:
                    selected = self.browse_entries[self.browse_cursor]
                    parts = [int(p) for p in selected.date.split("-")]
                    self.app.current_date = datetime.date(parts[0], parts[1], parts[2])
                    self.load_current_entry()
                return

        # In Read Mode:
        if self.mode == "read":
            if k_lower in ("e", "enter"):
                self.mode = "edit"
                self._sync_view_visibility()
                event.stop()
                return
            elif k_lower == "b":
                self.mode = "browse"
                self._sync_view_visibility()
                event.stop()
                return
            elif k_lower in ("left", "right", "h", "l", "0", "today"):
                # Strictly prevent date switching via arrows in Journal screen
                event.stop()
                return
            elif k_lower in ("d", "x"):
                if self.current_content.strip():
                    def on_confirm(ok: bool):
                        if ok:
                            date_str = self.app.current_date.strftime("%Y-%m-%d")
                            self.app.db.delete_journal_entry(date_str)
                            self.app.sync_engine.notify_local_mutation()
                            self.load_current_entry()
                            self.app.refresh_journal_markers()
                            self.app.set_toast("Journal entry deleted.")
                    self.app.push_screen(ConfirmModal("Delete this day's journal entry?"), on_confirm)
                return
            elif k in ("s", "S"):
                self.app.action_force_sync()
                return
            elif k in ("t", "T"):
                self.app.action_cycle_theme()
                return
            elif k_lower in ("escape", "j", "q"):
                self._flush_save()
                self.dismiss()
                return
