"""
lifeOS Projects & Next Actions Screen
=====================================
Brutally simple execution hierarchy:
- Active projects with clear Outcomes
- Startable NEXT actions (with estimates)
- WAITING actions with dependency blockers
- Someday parking & Archive
"""

from __future__ import annotations

from typing import Any, List, Optional
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Static

from lifeos.core.models import Action, ActionStatus, Project, ProjectStatus
from lifeos.ui.themes import Theme, fit
from lifeos.ui.widgets import ConfirmModal, HeaderBar, KeyChipBar, TextInputModal, ToastRail


class ProjectListView(Static):
    """Left sidebar: list of projects grouped by status."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs

        projects = getattr(self.screen, "projects", [])
        cursor = getattr(self.screen, "project_cursor_idx", 0)

        t = Text()
        t.append("PROJECTS\n", style=f"bold {p.accent_hi}")
        t.append(f"{g.line_horiz * 26}\n", style=f"{p.line}")

        if not projects:
            t.append("  No projects found.\n", style=f"{p.text_dim}")
            t.append("  Press [N] to add project", style=f"{p.text_faint}")
            return t

        for idx, proj in enumerate(projects):
            is_selected = (idx == cursor)
            rail = f"{g.line_vert} " if is_selected else "  "
            rail_style = p.accent_hi if is_selected else p.line
            t.append(rail, style=rail_style)

            # Area badge
            t.append(f"[{proj.area[:4]}] ", style=f"{p.accent}")

            # Title
            title_style = f"bold {p.text_hi}" if is_selected else p.text
            t.append(f"{proj.title[:16]:<16}\n", style=title_style)

        return t


class ProjectDetailView(Static):
    """Right pane: outcome, next actions, and waiting actions."""

    def render(self) -> Text:
        app = self.app
        th: Theme = app.theme_obj
        p = th.palette
        g = th.glyphs
        w = self.size.width or 80

        screen = self.screen
        projects = getattr(screen, "projects", [])
        p_cursor = getattr(screen, "project_cursor_idx", 0)
        a_cursor = getattr(screen, "action_cursor_idx", 0)
        focus_pane = getattr(screen, "focus_pane", "projects")

        t = Text()
        if not projects or p_cursor >= len(projects):
            t.append("Select or create a project to view outcome and next actions.", style=f"{p.text_dim}")
            return t

        proj: Project = projects[p_cursor]

        # Header
        t.append(f"PROJECT: {proj.title} ", style=f"bold {p.text_hi}")
        t.append(f"  {proj.status.value} · {proj.area}\n", style=f"{p.accent_hi}")
        t.append(f"Outcome: {proj.outcome or 'No outcome defined yet.'}\n", style=f"italic {p.text_dim}")
        t.append(f"{g.line_horiz * (w - 4)}\n\n", style=f"{p.line}")

        actions = proj.actions
        next_actions = [a for a in actions if a.status in (ActionStatus.NEXT, ActionStatus.DOING)]
        waiting_actions = [a for a in actions if a.status == ActionStatus.WAITING or a.is_blocked]
        done_actions = [a for a in actions if a.status == ActionStatus.DONE]

        # Render NEXT actions
        t.append("NEXT\n", style=f"bold {p.state_ok}")
        if not next_actions:
            t.append("  (No startable next action! Press 'A' to define physical step)\n", style=f"bold {p.state_warn}")
        else:
            for a in next_actions:
                global_idx = actions.index(a)
                is_selected = (focus_pane == "actions" and global_idx == a_cursor)
                rail = f" {g.line_vert} " if is_selected else "   "
                t.append(rail, style=f"bold {p.accent_hi}" if is_selected else f"{p.line}")

                cb = "[ ]"
                t.append(f"{cb} ", style=f"bold {p.accent_hi}" if is_selected else f"{p.text_dim}")
                t.append(f"{a.title:<46} ", style=f"bold {p.text_hi}" if is_selected else f"{p.text}")
                t.append(f"{a.estimate_minutes}m\n", style=f"{p.text_dim}")

        t.append("\n")

        # Render WAITING actions
        if waiting_actions:
            t.append("WAITING / BLOCKED\n", style=f"bold {p.state_warn}")
            for a in waiting_actions:
                global_idx = actions.index(a)
                is_selected = (focus_pane == "actions" and global_idx == a_cursor)
                rail = f" {g.line_vert} " if is_selected else "   "
                t.append(rail, style=f"bold {p.accent_hi}" if is_selected else f"{p.line}")

                blockers_str = ", ".join(a.blocker_titles) if a.blocker_titles else "waiting"
                t.append(f"[▪] {a.title:<44} ", style=f"{p.text_faint}")
                t.append(f"blocked by: {blockers_str}\n", style=f"{p.state_warn}")
            t.append("\n")

        # Render DONE actions count if any
        if done_actions:
            t.append(f"COMPLETED ({len(done_actions)} actions archived)\n", style=f"{p.text_faint}")

        return t


class ProjectScreen(Screen):
    """Full interactive Projects management screen."""

    def __init__(self):
        super().__init__()
        self.projects: List[Project] = []
        self.project_cursor_idx: int = 0
        self.action_cursor_idx: int = 0
        self.focus_pane: str = "projects"  # 'projects' or 'actions'

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="topbar")
        with Horizontal(id="project_split"):
            yield ProjectListView(id="project_sidebar")
            yield ProjectDetailView(id="project_content")
        yield ToastRail(id="toast")
        yield KeyChipBar(id="footer")

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
        self.query_one(ProjectListView).refresh()
        self.query_one(ProjectDetailView).refresh()

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
            self.query_one(ProjectListView).refresh()
            self.query_one(ProjectDetailView).refresh()
            return

        # Navigation
        if self.focus_pane == "projects":
            if k_lower in ("up", "k"):
                event.stop()
                if self.projects:
                    self.project_cursor_idx = (self.project_cursor_idx - 1) % len(self.projects)
                    self.action_cursor_idx = 0
                    self.query_one(ProjectListView).refresh()
                    self.query_one(ProjectDetailView).refresh()
                return
            elif k_lower in ("down", "j"):
                event.stop()
                if self.projects:
                    self.project_cursor_idx = (self.project_cursor_idx + 1) % len(self.projects)
                    self.action_cursor_idx = 0
                    self.query_one(ProjectListView).refresh()
                    self.query_one(ProjectDetailView).refresh()
                return
        else:
            # Action navigation
            if self.projects:
                curr_p = self.projects[self.project_cursor_idx]
                if curr_p.actions:
                    if k_lower in ("up", "k"):
                        event.stop()
                        self.action_cursor_idx = (self.action_cursor_idx - 1) % len(curr_p.actions)
                        self.query_one(ProjectDetailView).refresh()
                        return
                    elif k_lower in ("down", "j"):
                        event.stop()
                        self.action_cursor_idx = (self.action_cursor_idx + 1) % len(curr_p.actions)
                        self.query_one(ProjectDetailView).refresh()
                        return

        # CRUD actions
        if k_lower == "n":
            event.stop()
            self._action_add_project()
            return
        elif k_lower == "a":
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
                    # Set cursor to new project
                    for i, proj in enumerate(self.projects):
                        if proj.id == p.id:
                            self.project_cursor_idx = i
                            break
                    self.focus_pane = "projects"
                    self.query_one(ProjectListView).refresh()
                    self.query_one(ProjectDetailView).refresh()
                    self.app.set_toast(f"Created project '{clean_title}'")
                except ValueError as e:
                    self.app.set_toast(str(e))

        self.app.push_screen(TextInputModal("Enter project title:"), on_submit)

    def _action_add_action(self) -> None:
        if not self.projects:
            self.app.set_toast("Create a project first with 'N'")
            return
        curr_p = self.projects[self.project_cursor_idx]

        def on_submit(raw_title: Optional[str]):
            if raw_title and raw_title.strip():
                clean_raw = raw_title.strip()
                # Parse optional estimate like "Action title (45m)" or "Action title 45m"
                estimate = 30
                import re
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
                    # Switch focus to actions pane and highlight new action
                    self.focus_pane = "actions"
                    curr_refreshed = self.projects[self.project_cursor_idx]
                    for idx, a in enumerate(curr_refreshed.actions):
                        if a.id == act.id:
                            self.action_cursor_idx = idx
                            break
                    self.query_one(ProjectListView).refresh()
                    self.query_one(ProjectDetailView).refresh()
                    self.app.set_toast(f"Added next action: {clean_raw} ({estimate}m)")
                except ValueError as e:
                    self.app.set_toast(str(e))

        self.app.push_screen(TextInputModal(f"Add physical action to '{curr_p.title}' (e.g. 'Task name 45m'):"), on_submit)

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
