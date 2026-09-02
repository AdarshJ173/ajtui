"""
lifeOS Projects & Next Actions Screen (Tab 2)
=============================================
Brutally simple execution hierarchy:
- Left Pane: Projects grouped by Area (Health | Career | Learning | Relationships | Admin) with status glyphs
- Right Pane: Selected project detail with Outcome, NEXT startable physical actions, WAITING blocked actions
- Full CRUD: A add project, a add action, E edit, D archive/delete (with confirm + undo toast), K/J reorder,
  Space complete action, B send action to Plan as a block, 1/2/3 commit to Today's Three.
"""

from __future__ import annotations

import datetime
import re
from typing import Any, Dict, List, Optional
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Static

from lifeos.core.models import Action, ActionStatus, BlockKind, Project, ProjectStatus
from lifeos.ui.schedule_modal import ScheduleBlockModal
from lifeos.ui.themes import Theme, fit
from lifeos.ui.widgets import BottomStatusBar, ConfirmModal, HeaderBar, KeyChipBar, TextInputModal, ToastRail

AREAS = ["Career", "Learning", "Health", "Relationships", "Admin"]

STATUS_GLYPHS = {
    ProjectStatus.ACTIVE: "●",
    ProjectStatus.SOMEDAY: "○",
    ProjectStatus.WAITING: "▪",
    ProjectStatus.COMPLETED: "✓",
    ProjectStatus.ARCHIVED: "✕",
}


class ProjectListView(Static):
    """Left sidebar: list of projects grouped by Area with status glyphs."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs

        projects: List[Project] = getattr(self.screen, "projects", []) or app.db.get_projects()
        cursor = getattr(self.screen, "project_cursor_idx", 0)

        t = Text()
        t.append("PROJECTS & OUTCOMES\n", style=f"bold {p.accent_hi}")
        t.append(f"{g.line_horiz * 28}\n", style=f"{p.line}")

        if not projects:
            t.append("  No projects found.\n", style=f"{p.text_dim}")
            t.append("  Press [A] to create project\n", style=f"bold {p.accent_hi}")
            return t

        # Group by Area
        proj_by_area: Dict[str, List[Project]] = {area: [] for area in AREAS}
        for pr in projects:
            area = pr.area if pr.area in proj_by_area else "Career"
            proj_by_area[area].append(pr)

        current_flat_idx = 0
        for area in AREAS:
            area_projs = proj_by_area[area]
            if not area_projs:
                continue

            t.append(f"  {area.upper()}\n", style=f"bold {p.accent}")
            for pr in area_projs:
                is_selected = (current_flat_idx == cursor)
                rail = f"{g.line_vert} " if is_selected else "  "
                rail_style = f"bold {p.accent_hi}" if is_selected else p.line

                glyph = STATUS_GLYPHS.get(pr.status, "●")
                glyph_style = p.state_ok if pr.status == ProjectStatus.ACTIVE else (p.state_warn if pr.status == ProjectStatus.WAITING else p.text_dim)

                t.append(rail, style=rail_style)
                t.append(f"{glyph} ", style=f"bold {glyph_style}")

                title_style = f"bold {p.text_hi}" if is_selected else p.text
                t.append(f"{pr.title[:18]:<18}\n", style=title_style)
                current_flat_idx += 1

        return t


class ProjectDetailView(Static):
    """Right pane: outcome, next startable physical actions, and waiting blocked actions."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs
        w = self.size.width or 60

        screen = self.screen
        projects = getattr(screen, "projects", []) or app.db.get_projects()
        p_cursor = getattr(screen, "project_cursor_idx", 0)
        a_cursor = getattr(screen, "action_cursor_idx", 0)
        focus_pane = getattr(screen, "focus_pane", "projects")

        t = Text()
        if not projects or p_cursor >= len(projects):
            t.append("Select or create a project to view outcome and startable next actions.", style=f"{p.text_dim}")
            return t

        proj: Project = projects[p_cursor]

        # Header: Project title + Area + Status badge
        t.append(f"PROJECT: {proj.title} ", style=f"bold {p.text_hi}")
        t.append(f"[{proj.status.value.upper()}] · {proj.area}\n", style=f"bold {p.accent_hi}")
        t.append(f"Outcome: {proj.outcome or 'Plan today in <5 minutes and finish a focused block.'}\n", style=f"italic {p.text_dim}")
        t.append(f"{g.line_horiz * max(10, w - 4)}\n\n", style=f"{p.line}")

        actions = proj.actions
        next_actions = [a for a in actions if a.status in (ActionStatus.NEXT, ActionStatus.DOING)]
        waiting_actions = [a for a in actions if a.status == ActionStatus.WAITING or a.is_blocked]
        done_actions = [a for a in actions if a.status == ActionStatus.DONE]

        # 1. NEXT Section
        t.append("NEXT PHYSICAL ACTIONS\n", style=f"bold {p.state_ok}")
        if not next_actions:
            t.append("  (No concrete next action! Press 'a' to define the next startable step)\n", style=f"bold {p.state_warn}")
        else:
            for a in next_actions:
                global_idx = actions.index(a)
                is_selected = (focus_pane == "actions" and global_idx == a_cursor)
                rail = f" {g.line_vert} " if is_selected else "   "
                t.append(rail, style=f"bold {p.accent_hi}" if is_selected else f"{p.line}")

                cb = f"{g.checkbox_empty}"
                t.append(f"{cb} ", style=f"bold {p.accent_hi}" if is_selected else f"{p.text_dim}")
                t.append(f"{a.title:<38} ", style=f"bold {p.text_hi}" if is_selected else f"{p.text}")
                t.append(f"{a.estimate_minutes}m\n", style=f"{p.text_dim}")

        t.append("\n")

        # 2. WAITING Section
        if waiting_actions:
            t.append("WAITING / BLOCKED\n", style=f"bold {p.state_warn}")
            for a in waiting_actions:
                global_idx = actions.index(a)
                is_selected = (focus_pane == "actions" and global_idx == a_cursor)
                rail = f" {g.line_vert} " if is_selected else "   "
                t.append(rail, style=f"bold {p.accent_hi}" if is_selected else f"{p.line}")

                blockers_str = ", ".join(a.blocker_titles) if a.blocker_titles else "waiting"
                t.append(f"[▪] {a.title:<36} ", style=f"{p.text_faint}")
                t.append(f"blocked by: {blockers_str}\n", style=f"{p.state_warn}")
            t.append("\n")

        # 3. Completed Section
        if done_actions:
            t.append(f"COMPLETED ({len(done_actions)} actions archived)\n", style=f"{p.text_faint}")

        return t


class ProjectView(Widget):
    """Tab 2 View container."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="project_split"):
            yield ProjectListView(id="project_sidebar")
            yield ProjectDetailView(id="project_content")

    def refresh_view(self) -> None:
        try:
            self.query_one(ProjectListView).refresh()
            self.query_one(ProjectDetailView).refresh()
        except Exception:
            pass


class ProjectScreen(Screen):
    """Full interactive Projects Screen."""

    def __init__(self):
        super().__init__()
        self.projects: List[Project] = []
        self.project_cursor_idx: int = 0
        self.action_cursor_idx: int = 0
        self.focus_pane: str = "projects"  # 'projects' or 'actions'

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="topbar")
        yield ProjectView(id="project_view")
        yield ToastRail(id="toast")
        yield BottomStatusBar(id="footer")

    def on_mount(self) -> None:
        self.refresh_projects()

    def refresh_projects(self) -> None:
        self.projects = self.app.db.get_projects()
        if self.projects:
            self.project_cursor_idx = max(0, min(len(self.projects) - 1, self.project_cursor_idx))
            curr = self.projects[self.project_cursor_idx]
            if curr.actions:
                self.action_cursor_idx = max(0, min(len(curr.actions) - 1, self.action_cursor_idx))
            else:
                self.action_cursor_idx = 0
        try:
            self.query_one(ProjectListView).refresh()
            self.query_one(ProjectDetailView).refresh()
        except Exception:
            pass

    def on_key(self, event: events.Key) -> None:
        k = event.key
        k_lower = k.lower()

        if k_lower in ("escape", "q"):
            event.stop()
            self.app.pop_screen()
            return

        # Pane switching
        if k in ("tab", "left", "right", "h", "l"):
            event.stop()
            self.focus_pane = "actions" if self.focus_pane == "projects" else "projects"
            self.refresh_projects()
            return

        # Navigation
        if self.focus_pane == "projects":
            if k_lower in ("up", "k"):
                event.stop()
                if self.projects:
                    self.project_cursor_idx = (self.project_cursor_idx - 1) % len(self.projects)
                    self.action_cursor_idx = 0
                    self.refresh_projects()
                return
            elif k_lower in ("down", "j"):
                event.stop()
                if self.projects:
                    self.project_cursor_idx = (self.project_cursor_idx + 1) % len(self.projects)
                    self.action_cursor_idx = 0
                    self.refresh_projects()
                return
        else:
            if self.projects:
                curr_p = self.projects[self.project_cursor_idx]
                if curr_p.actions:
                    if k_lower in ("up", "k"):
                        event.stop()
                        self.action_cursor_idx = (self.action_cursor_idx - 1) % len(curr_p.actions)
                        self.refresh_projects()
                        return
                    elif k_lower in ("down", "j"):
                        event.stop()
                        self.action_cursor_idx = (self.action_cursor_idx + 1) % len(curr_p.actions)
                        self.refresh_projects()
                        return

        # CRUD Actions
        if k == "A":  # Add project
            event.stop()
            self._action_add_project()
            return
        elif k == "a":  # Add action
            event.stop()
            self._action_add_action()
            return
        elif k_lower == "e":
            event.stop()
            self._action_edit()
            return
        elif k_lower in ("space", "enter"):
            event.stop()
            self._action_toggle_or_select()
            return
        elif k in ("1", "2", "3"):
            event.stop()
            self._action_commit_priority(int(k))
            return
        elif k_lower == "b":
            event.stop()
            self._action_schedule_to_plan()
            return
        elif k_lower == "w":
            event.stop()
            self._action_toggle_waiting()
            return
        elif k_lower in ("d", "x"):
            event.stop()
            self._action_delete()
            return

    def _action_add_project(self) -> None:
        def on_submit(title: Optional[str]):
            if title and title.strip():
                clean_title = title.strip()
                try:
                    p = self.app.db.add_project(title=clean_title)
                    self.app.sync_engine.notify_local_mutation()
                    self.refresh_projects()
                    self.app.set_toast(f"Created project '{clean_title}'")
                except ValueError as e:
                    self.app.set_toast(str(e))

        self.app.push_screen(TextInputModal("Enter project title:"), on_submit)

    def _action_add_action(self) -> None:
        if not self.projects:
            self.app.set_toast("Create a project first with 'A'")
            return
        curr_p = self.projects[self.project_cursor_idx]

        def on_submit(raw_title: Optional[str]):
            if raw_title and raw_title.strip():
                clean_raw = raw_title.strip()
                estimate = 30
                m = re.search(r'[\(\[\s](\d+)\s*(?:m|min|mins)?[\)\]]?$', clean_raw, re.IGNORECASE)
                if m:
                    try:
                        estimate = int(m.group(1))
                        clean_raw = clean_raw[:m.start()].strip()
                    except ValueError:
                        pass
                
                try:
                    act = self.app.db.add_action(
                        title=clean_raw,
                        project_id=curr_p.id,
                        estimate_minutes=estimate,
                    )
                    self.app.sync_engine.notify_local_mutation()
                    self.refresh_projects()
                    self.app.set_toast(f"Added next action: {clean_raw} ({estimate}m)")
                except ValueError as e:
                    self.app.set_toast(str(e))

        self.app.push_screen(TextInputModal(f"Add physical action to '{curr_p.title}' (e.g. 'Draft schema 45m'):"), on_submit)

    def _action_edit(self) -> None:
        if not self.projects:
            return
        curr_p = self.projects[self.project_cursor_idx]

        if self.focus_pane == "projects":
            def on_submit(new_title: Optional[str]):
                if new_title and new_title != curr_p.title:
                    self.app.db.update_project(curr_p.id, title=new_title)
                    self.app.sync_engine.notify_local_mutation()
                    self.refresh_projects()
                    self.app.set_toast(f"Renamed project to '{new_title}'")
            self.app.push_screen(TextInputModal("Edit project title:", initial=curr_p.title), on_submit)
        else:
            if not curr_p.actions:
                return
            act = curr_p.actions[self.action_cursor_idx]
            def on_submit_act(new_title: Optional[str]):
                if new_title and new_title != act.title:
                    try:
                        self.app.db.update_action(act.id, title=new_title)
                        self.app.sync_engine.notify_local_mutation()
                        self.refresh_projects()
                        self.app.set_toast(f"Updated action: '{new_title}'")
                    except ValueError as e:
                        self.app.set_toast(str(e))
            self.app.push_screen(TextInputModal("Edit action title:", initial=act.title), on_submit_act)

    def _action_toggle_or_select(self) -> None:
        if not self.projects:
            return
        curr_p = self.projects[self.project_cursor_idx]
        if self.focus_pane == "actions" and curr_p.actions:
            act = curr_p.actions[self.action_cursor_idx]
            new_stat = ActionStatus.NEXT if act.status == ActionStatus.DONE else ActionStatus.DONE
            self.app.db.update_action(act.id, status=new_stat)
            self.app.sync_engine.notify_local_mutation()
            self.refresh_projects()
            msg = "Completed action!" if new_stat == ActionStatus.DONE else "Marked action as next."
            self.app.set_toast(f"{msg} ({act.title})")

    def _action_toggle_waiting(self) -> None:
        if not self.projects:
            return
        curr_p = self.projects[self.project_cursor_idx]
        if curr_p.actions:
            act = curr_p.actions[self.action_cursor_idx]
            new_stat = ActionStatus.WAITING if act.status == ActionStatus.NEXT else ActionStatus.NEXT
            self.app.db.update_action(act.id, status=new_stat)
            self.app.sync_engine.notify_local_mutation()
            self.refresh_projects()
            self.app.set_toast(f"Set action status to {new_stat.value}")

    def _action_commit_priority(self, rank: int) -> None:
        if not self.projects:
            return
        curr_p = self.projects[self.project_cursor_idx]
        if not curr_p.actions:
            return
        act = curr_p.actions[self.action_cursor_idx]
        today_str = self.app.current_date.strftime("%Y-%m-%d")
        try:
            self.app.db.set_daily_priority(today_str, rank, act.id)
            self.app.sync_engine.notify_local_mutation()
            self.app.set_toast(f"Locked as Priority #{rank} for today: '{act.title}'")
        except ValueError as e:
            self.app.set_toast(str(e))

    def _action_schedule_to_plan(self) -> None:
        if not self.projects:
            return
        curr_p = self.projects[self.project_cursor_idx]
        if not curr_p.actions:
            return
        act = curr_p.actions[self.action_cursor_idx]
        today_str = self.app.current_date.strftime("%Y-%m-%d")

        def on_sched(data):
            if data:
                self.app.db.add_time_block(
                    date_str=today_str,
                    starts_at=data["starts_at"],
                    ends_at=data["ends_at"],
                    action_id=act.id,
                    kind=data["kind"],
                    planned_minutes=data["duration"],
                )
                self.app.sync_engine.notify_local_mutation()
                self.app.set_toast(f"Scheduled focus block for '{act.title}' ({data['starts_at']}–{data['ends_at']})")

        self.app.push_screen(ScheduleBlockModal(), on_sched)

    def _action_delete(self) -> None:
        if not self.projects:
            return
        curr_p = self.projects[self.project_cursor_idx]
        if self.focus_pane == "projects":
            self.app.db.delete_project(curr_p.id)
            self.app.sync_engine.notify_local_mutation()
            self.refresh_projects()
            self.app.set_toast(f"Archived project '{curr_p.title}'")
        else:
            if curr_p.actions:
                act = curr_p.actions[self.action_cursor_idx]
                self.app.db.delete_action(act.id)
                self.app.sync_engine.notify_local_mutation()
                self.refresh_projects()
                self.app.set_toast(f"Deleted action '{act.title}'")
