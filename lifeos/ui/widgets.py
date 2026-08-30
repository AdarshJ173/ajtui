"""
lifeOS Reusable Crafted UI Widgets
==================================
Pixel-perfect terminal components with rich typography, instant responsiveness,
collision-free calendar matrices, and live sync badges.
"""

from __future__ import annotations

import calendar
import datetime
from typing import Dict, List, Optional, Set, Tuple

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

from lifeos.core.models import Completion, SyncStateEnum, Task
from lifeos.ui.themes import (
    BOOT_STAGES,
    Theme,
    dim_style,
    ease_out_back,
    ease_out_cubic,
    fit,
    progress_bar_cells,
    rich_style,
    sparkline,
)


class KeyChipBar(Static):
    """Refined keyboard-shortcut hint bar styled as chips."""

    def render(self) -> Text:
        th: Theme = self.app.theme_obj
        p = th.palette
        app = self.app

        active_screen = getattr(app, "screen", None)
        if active_screen and getattr(active_screen, "__class__", None).__name__ == "JournalScreen":
            js = active_screen
            if getattr(js, "mode", "") == "edit":
                chips = [
                    ("Esc / Ctrl+S", "Save & Exit"),
                ]
            elif getattr(js, "mode", "") == "browse":
                chips = [
                    ("↵", "Open"), ("↑/↓", "Select"), ("Esc", "Back"), ("Q", "Quit"),
                ]
            else:
                chips = [
                    ("E/↵", "Write"), ("B", "Browse Past"), ("D", "Del"),
                    ("Esc", "Habits"), ("S", "Sync"), ("T", "Theme"), ("Q", "Quit"),
                ]
        elif getattr(app, "calendar_active", False):
            chips = [
                ("↵", "Jump"), ("Esc", "Back"), ("←/→", "Day"),
                ("↑/↓", "Week"), ("0", "Today"), ("J", "Journal"),
                ("S", "Sync"), ("T", "Theme"), ("Q", "Quit"),
            ]
        else:
            chips = [
                ("↵", "Toggle"), ("A", "Add"), ("E", "Rename"), ("D", "Del"),
                ("K/J", "Move"), ("←/→", "Date"), ("C", "Cal"),
                ("J", "Journal"), ("S", "Sync"), ("T", "Theme"), ("Q", "Quit"),
            ]

        w = self.size.width or 80
        t = Text()
        for key, label in chips:
            t.append(" [", style=f"{p.line}")
            t.append(key, style=f"bold {p.accent_hi}")
            t.append("] ", style=f"{p.line}")
            t.append(label, style=f"{p.text_dim}")

        if len(t.plain) > w:
            t = Text()
            for key, label in chips:
                t.append("[", style=f"{p.line}")
                t.append(key, style=f"bold {p.accent_hi}")
                t.append("]", style=f"{p.line}")
                t.append(label[0] if label else "", style=f"{p.text_dim}")
        return t


class HeaderBar(Static):
    """Engineered header: Logo mark · viewed date · sync badge · streak · live clock."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs

        w = self.size.width if self.size.width > 20 else 80
        t = Text()

        # Logo mark + wordmark
        t.append(f"{g.logo} ", style=f"bold {p.accent_hi}")
        t.append("lifeOS", style=f"bold {p.text_hi}")
        t.append(" daily ", style=f"bold {p.accent}")
        t.append(f"{g.line_v} ", style=f"{p.line}")

        # Date string with era tag
        view_date = app.current_date
        today = datetime.date.today()
        is_today = view_date == today
        date_str = view_date.strftime("%a, %b %d %Y")
        tag = "TODAY" if is_today else ("PAST" if view_date < today else "FUTURE")
        tag_color = p.state_ok if is_today else (
            p.text_dim if view_date < today else p.state_warn
        )
        t.append(date_str, style=f"bold {p.text_hi}")
        t.append(f" {tag}", style=f"bold {tag_color}")

        # Middle / Right: Sync status + streak + clock
        sync_state = getattr(app, "sync_state", None)
        sync_text = Text()
        if sync_state:
            st = sync_state.status
            if st == SyncStateEnum.LIVE:
                sync_text.append(f"{g.cloud_live} live", style=f"bold {p.state_ok}")
            elif st == SyncStateEnum.SYNCING:
                sync_text.append(f"{g.cloud_syncing} syncing", style=f"bold {p.state_warn}")
            elif st == SyncStateEnum.CONFLICT:
                sync_text.append(f"{g.cloud_conflict} conflict", style=f"bold {p.danger}")
            elif st == SyncStateEnum.OFFLINE:
                sync_text.append(f"{g.cloud_offline} offline", style=f"{p.text_faint}")
            else:
                sync_text.append(f"{g.cloud_offline} local", style=f"{p.text_faint}")

        streak_val = getattr(app, "streak_count", 0)
        flick = getattr(app, "flame_lit", True) and streak_val > 0
        flame_style = f"bold {p.hot}" if flick else (
            f"{p.hot_dim}" if streak_val > 0 else f"{p.text_faint}"
        )
        now_time = getattr(app, "now_time_str", datetime.datetime.now().strftime("%H:%M:%S"))

        right = Text()
        if sync_text:
            right.append_text(sync_text)
            right.append(f"  {g.line_v}  ", style=f"{p.line}")

        right.append(f"{g.flame} ", style=flame_style)
        right.append(
            f"{streak_val}d", style=f"bold {p.hot if streak_val > 0 else p.text_dim}"
        )
        right.append(f"  {g.line_v}  ", style=f"{p.line}")
        right.append(now_time, style=f"bold {p.text_hi}")

        pad = max(1, w - len(t.plain) - len(right.plain) - 2)
        t.append(" " * pad)
        t.append_text(right)
        return t


class HeroBanner(Static):
    """Contextual status line — dynamic motivational headline."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs
        m = th.messages

        view_date = app.current_date
        today = datetime.date.today()
        tasks = app.tasks
        comps = app.completions
        total = len(tasks)
        done = sum(1 for t in tasks if comps.get(t.id, Completion(t.id, "", False)).done)

        if view_date > today:
            msg, color = m.hero_future, p.state_warn
            sub = m.sub_future
        elif view_date < today:
            msg, color = m.hero_history, p.text_dim
            pct = int(done / total * 100) if total else 0
            sub = m.sub_history.format(done=done, total=total, pct=pct)
        else:
            if total == 0:
                msg, color = m.momentum_start, p.accent
                sub = f"Press {m.empty_hint} to register your foundational daily habits."
            elif done == total:
                msg, color = m.hero_done, p.state_ok
                sub = m.sub_done
            elif done == 0:
                msg, color = m.hero_today, p.accent
                sub = m.sub_today_zero.format(total=total)
            else:
                msg, color = m.hero_press_on, p.accent_hi
                sub = m.sub_today_mid.format(done=done, total=total, left=total - done)

        t = Text()
        t.append(f"{g.spark} ", style=f"bold {color}")
        t.append(msg, style=f"bold {p.text_hi}")
        t.append(f"\n{sub}", style=f"{p.text_dim}")
        return t


class TaskListView(Static):
    """Routine habits list with clean cursor, checkbox toggling, and fast animations."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs
        m = th.messages

        tasks = app.tasks
        comps = app.completions
        cursor = app.cursor_idx
        w = max(30, self.size.width - 4)

        if not tasks:
            t = Text()
            logo = th.ascii_logo
            t.append("\n")
            for line in logo:
                t.append(f"  {line}\n", style=f"bold {p.accent}")
            t.append(f"\n  {m.empty_title}\n", style=f"bold {p.text_hi}")
            t.append(f"  {g.spark} {m.empty_invite} {m.empty_hint}\n", style=f"{p.accent}")
            return t

        flip = getattr(app, "flip_anims", {})

        t = Text()
        for idx, task in enumerate(tasks):
            is_selected = (idx == cursor) and not getattr(app, "calendar_active", False)
            is_done = comps.get(task.id, Completion(task.id, "", False)).done

            # Selection band
            if is_selected:
                prefix = f"{g.w_right} "
                prefix_style = f"bold {p.accent_hi}"
                row_bg = f"on {p.band_hot}" if p.band_hot and th.caps.colorful else ""
            else:
                prefix = "  "
                prefix_style = f"{p.text_faint}"
                row_bg = ""

            # Checkbox & title
            if is_done:
                check_icon = g.check
                check_style = f"bold {p.state_ok}"
                title_style = f"{p.text_dim}"
            else:
                check_icon = g.open_box
                check_style = f"bold {p.accent}" if is_selected else f"{p.text_faint}"
                title_style = f"bold {p.text_hi}" if is_selected else f"{p.text}"

            spark_style = None
            if task.id in flip:
                frame, total_f, checking = flip[task.id]
                prog = frame / max(1, total_f - 1)
                if prog < 0.5:
                    check_icon = g.check_flash if checking else g.open_box
                    check_style = f"bold {p.accent_hi}"
                    spark_style = f"bold {p.accent_hi}"
                else:
                    check_icon = g.check if checking else g.open_box
                    check_style = f"bold {p.state_ok}" if checking else f"bold {p.accent}"
                    title_style = (
                        f"bold {p.state_ok}" if checking else title_style
                    )
                    spark_style = dim_style(p.state_ok) if checking else None

            line = Text()
            line.append(prefix, style=prefix_style)
            line.append("[", style=f"{p.line}")
            line.append(check_icon, style=check_style)
            line.append("] ", style=f"{p.line}")
            line.append(f"{idx + 1:2d}. ", style=f"{p.text_faint}")
            line.append(fit(task.title, w - 9), style=title_style)

            plain_len = len(line.plain)
            if plain_len < w:
                line.append(" " * (w - plain_len))
            if row_bg:
                line.stylize(row_bg)

            t.append_text(line)
            t.append("\n")

        return t


class MonthCalendarView(Static):
    """
    Fixed-width, non-wrapping Month Calendar with completion semaphores and journal markers.
    Guaranteed 21-character grid that never wraps or collides.
    """

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs

        cal_date = getattr(app, "cal_focus_date", datetime.date.today())
        stats = getattr(app, "month_stats", {})
        journal_dates: Set[str] = getattr(app, "journal_dates_this_month", set())
        uni = th.caps.unicode

        # Slide offset during a month transition
        off = 0
        if getattr(app, "cal_slide", (0, 0, 0))[0] > 0:
            frame, total_f, direction = app.cal_slide
            prog = ease_out_cubic(frame / max(1, total_f - 1))
            off = int(round((1.0 - prog) * 4)) * direction
        pad = " " * max(0, off)

        t = Text()
        mode_tag = " ·BROWSING" if getattr(app, "calendar_active", False) else ""
        title = f"{calendar.month_name[cal_date.month]} {cal_date.year}"
        t.append(pad, style="")
        t.append(title, style=f"bold {p.accent_hi}")
        if mode_tag:
            t.append(mode_tag, style=f"bold {p.state_warn}")
        t.append("\n")

        # 7 columns x 3 chars = 21 chars wide (never wraps in standard 37w panel)
        t.append(pad + "Mo Tu We Th Fr Sa Su\n", style=f"{p.text_faint}")

        matrix = calendar.monthcalendar(cal_date.year, cal_date.month)
        today = datetime.date.today()
        current = getattr(app, "current_date", datetime.date.today())

        for week in matrix:
            row = Text(pad)
            for day in week:
                if day == 0:
                    row.append("   ")
                    continue
                d_obj = datetime.date(cal_date.year, cal_date.month, day)
                d_str = d_obj.strftime("%Y-%m-%d")
                done_c, total_c = stats.get(d_str, (0, 0))
                has_journal = d_str in journal_dates

                # Completion marker
                if total_c > 0 and done_c >= total_c:
                    marker, marker_color = g.done, p.state_ok
                elif done_c > 0:
                    marker, marker_color = g.partial, p.state_warn
                elif has_journal:
                    marker, marker_color = g.journal, p.accent_hi
                else:
                    marker, marker_color = ("·" if uni else "."), p.text_faint

                day_str = f"{day:2d}"
                _, on_color = rich_style(p.on_accent)
                _, ac_hi_color = rich_style(p.accent_hi)
                _, ac_color = rich_style(p.accent)

                if d_obj == cal_date and getattr(app, "calendar_active", False):
                    row.append(day_str, style=f"bold {on_color} on {ac_hi_color}")
                elif d_obj == current:
                    row.append(day_str, style=f"bold {on_color} on {ac_color}")
                elif d_obj == today:
                    row.append(day_str, style=f"bold underline {p.accent_hi}")
                elif has_journal:
                    row.append(day_str, style=f"bold {p.accent_hi}")
                else:
                    row.append(day_str, style=f"{p.text}")

                row.append(marker, style=f"bold {marker_color}")
            t.append_text(row)
            t.append("\n")

        t.append("\n")
        t.append(f"{g.done} done  ", style=f"{p.state_ok}")
        t.append(f"{g.partial} part  ", style=f"{p.state_warn}")
        t.append(f"{g.empty} none  ", style=f"{p.text_faint}")
        t.append(f"{g.journal} journal", style=f"bold {p.accent_hi}")
        return t


class MomentumDock(Static):
    """Data-viz dock: Smooth Braille progress bar + 7-day trend."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs
        m = th.messages

        tasks = app.tasks
        comps = app.completions
        total = len(tasks)
        done = sum(1 for t in tasks if comps.get(t.id, Completion(t.id, "", False)).done)

        display_frac = getattr(app, "anim_progress", 0.0)

        w = self.size.width or 80
        bar_w = max(12, min(50, w - 24))
        uni = th.caps.unicode

        cells = progress_bar_cells(display_frac, bar_w, uni)
        full_count = 0
        for c in cells:
            if c == ("█" if uni else "#"):
                full_count += 1
            else:
                break

        pct = int(round(display_frac * 100))
        spark = sparkline(g, getattr(app, "sparkline_data", [0.0] * 7))

        # Micro-copy
        if total == 0:
            m_copy = m.momentum_start
        elif done == total:
            m_copy = m.momentum_done
        elif done == total - 1:
            m_copy = m.momentum_final
        elif done == 0:
            m_copy = m.momentum_start
        elif done == 1:
            m_copy = m.momentum_open
        elif done >= total // 2:
            m_copy = m.momentum_close.format(n=total - done)
        else:
            m_copy = m.momentum_mid

        t = Text()
        # Line 1: counts + trend
        t.append(f"{g.bolt} ", style=f"bold {p.accent}")
        t.append(f"{done}/{total}", style=f"bold {p.text_hi}")
        t.append(f" complete", style=f"{p.text_dim}")
        t.append(f"    7d trend ", style=f"{p.text_faint}")
        t.append(spark, style=f"bold {p.state_ok}")
        t.append("\n")

        # Line 2: the smooth segmented bar
        t.append(g.bar_left, style=f"bold {p.accent}")
        t.append("".join(cells[:full_count]), style=f"bold {p.accent}")
        if full_count < len(cells):
            t.append(cells[full_count], style=f"bold {p.accent_hi}")
            rest = "".join(cells[full_count + 1:])
            if rest:
                t.append(rest, style=f"{p.line}")
        t.append(g.bar_right, style=f"bold {p.accent}")
        t.append(f" {pct:>3d}%", style=f"bold {p.accent_hi}")
        t.append("\n")

        # Line 3: momentum voice
        t.append(f"{g.spark} ", style=f"{p.accent}")
        t.append(m_copy, style=f"{p.text_dim}")
        return t


class ToastRail(Static):
    """Ephemeral feedback line."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs
        msg = getattr(app, "toast_message", "")
        if not msg:
            return Text()
        t = Text()
        t.append(f"{g.spark} ", style=f"bold {p.accent_hi}")
        t.append(msg, style=f"bold {p.text_hi}")
        return t


class BootOverlay(Static):
    """Fast skippable boot splash."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs

        frame = getattr(app, "boot_frame", 0)
        total = th.anim.boot_frames
        prog = frame / max(1, total - 1)

        t = Text()
        logo = th.ascii_logo
        reveal = ease_out_back(prog)
        visible_cols = max(1, int(round(len(logo[0]) * min(1.0, reveal))))
        for line in logo:
            t.append(line[:visible_cols], style=f"bold {p.accent_hi}")
            t.append("\n")
        t.append("lifeOS ", style=f"bold {p.text_hi}")
        t.append("daily", style=f"bold {p.accent}")
        t.append("\n")

        stage_idx = min(len(BOOT_STAGES) - 1, int(prog * len(BOOT_STAGES)))
        for i, stage in enumerate(BOOT_STAGES):
            if i < stage_idx:
                t.append(f"  {g.check} {stage}\n", style=f"{p.state_ok}")
            elif i == stage_idx:
                t.append(f"  {g.w_right} {stage}\n", style=f"bold {p.accent_hi}")
            else:
                t.append(f"  · {stage}\n", style=f"{p.text_faint}")
        return t


class TextInputModal(ModalScreen[Optional[str]]):
    """Minimal modal for Add/Edit."""

    def __init__(self, prompt: str, initial: str = ""):
        super().__init__()
        self.prompt_text = prompt
        self.initial_text = initial

    def compose(self) -> ComposeResult:
        with Vertical(id="modal_box"):
            yield Label(self.prompt_text, id="modal_prompt")
            yield Input(value=self.initial_text, id="modal_input")

    def on_mount(self) -> None:
        th: Theme = self.app.theme_obj
        p = th.palette
        box = self.query_one("#modal_box")
        box.styles.background = p.panel or "default"
        box.styles.border = ("round", p.accent or "default")
        box.styles.padding = (1, 2)
        box.styles.width = 60
        box.styles.height = "auto"
        prompt = self.query_one("#modal_prompt")
        prompt.styles.color = p.text_hi or "default"
        prompt.styles.text_style = "bold"
        prompt.styles.margin = (0, 0, 1, 0)
        inp = self.query_one(Input)
        inp.focus()

    @on(Input.Submitted, "#modal_input")
    def on_submit(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)


class ConfirmModal(ModalScreen[bool]):
    """Confirmation modal for destructive actions."""

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="modal_box"):
            yield Label(self.message, id="modal_prompt")
            yield Label("[Y] Confirm  ·  [N / Esc] Cancel", id="modal_hint")

    def on_mount(self) -> None:
        th: Theme = self.app.theme_obj
        p = th.palette
        box = self.query_one("#modal_box")
        box.styles.background = p.panel or "default"
        box.styles.border = ("round", p.danger or "red")
        box.styles.padding = (1, 2)
        box.styles.width = 56
        box.styles.height = "auto"
        prompt = self.query_one("#modal_prompt")
        prompt.styles.color = p.text_hi or "default"
        prompt.styles.text_style = "bold"
        hint = self.query_one("#modal_hint")
        hint.styles.color = p.text_dim or "default"
        hint.styles.margin = (1, 0, 0, 0)

    def on_key(self, event: events.Key) -> None:
        if event.key.lower() in ("y", "enter"):
            self.dismiss(True)
        elif event.key.lower() in ("n", "escape"):
            self.dismiss(False)
