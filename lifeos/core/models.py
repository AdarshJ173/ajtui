"""
lifeOS Core Data Models
=======================
Typed domain models shared across database layers, sync engine, and UI components.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple


def generate_uuid() -> str:
    """Generate a clean UUIDv4 string."""
    return str(uuid.uuid4())


def current_iso_time() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ProjectStatus(str, Enum):
    ACTIVE = "active"
    SOMEDAY = "someday"
    WAITING = "waiting"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ActionStatus(str, Enum):
    INBOX = "inbox"
    NEXT = "next"
    SCHEDULED = "scheduled"
    DOING = "doing"
    WAITING = "waiting"
    DONE = "done"
    CANCELLED = "cancelled"


class BlockStatus(str, Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    OVERRUN = "overrun"


class BlockKind(str, Enum):
    DEEP_WORK = "deep_work"
    ROUTINE = "routine"
    ADMIN = "admin"
    BUFFER = "buffer"


class EnergyLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class InboxStatus(str, Enum):
    UNPROCESSED = "unprocessed"
    CONVERTED = "converted"
    ARCHIVED = "archived"
    DISCARDED = "discarded"


class SyncStateEnum(str, Enum):
    LIVE = "live"
    SYNCING = "syncing"
    OFFLINE = "offline"
    CONFLICT = "conflict"
    LOCAL_ONLY = "local_only"


# ---------------------------------------------------------------------------
# Action Invariant & Title Validation
# ---------------------------------------------------------------------------

VAGUE_ACTION_STARTERS = {
    "do project", "work on", "work", "do work", "do stuff",
    "project", "handle", "manage", "study", "code", "research", "look into"
}

def is_valid_physical_action(title: str) -> Tuple[bool, str]:
    """
    Validate that an action title describes a concrete, physical next action.
    Rejects empty titles, ultra-short titles (<3 chars), or vague project references.
    """
    cleaned = title.strip().lower()
    if not cleaned:
        return False, "Action title cannot be empty. What is the next physical action?"
    if len(cleaned) < 3:
        return False, "Action title too short. Please describe a concrete startable step."
    if cleaned in VAGUE_ACTION_STARTERS or any(cleaned.startswith(f"{v} ") for v in ["do", "work on", "manage", "handle", "fix things"]):
        if len(cleaned.split()) <= 2:
            return False, "Too vague. What is the exact next physical action (e.g. 'Draft schema in local.py')?"
    return True, ""


# ---------------------------------------------------------------------------
# Domain Models
# ---------------------------------------------------------------------------

@dataclass
class Task:
    """Daily recurring routine / habit."""
    id: int
    title: str
    sort_order: int
    created_at: str = ""
    updated_at: str = ""
    uuid: str = field(default_factory=generate_uuid)
    active: bool = True


@dataclass
class Completion:
    """Per-day checkoff for a routine task."""
    task_id: int
    date: str
    done: bool
    id: Optional[int] = None
    uuid: str = field(default_factory=generate_uuid)
    task_uuid: str = ""
    completed_at: str = ""
    updated_at: str = ""


@dataclass
class JournalEntry:
    """Daily plain-text journal entry."""
    date: str
    content: str
    word_count: int = 0
    id: Optional[int] = None
    uuid: str = field(default_factory=generate_uuid)
    created_at: str = ""
    updated_at: str = ""
    mtime: float = 0.0

    def calculate_word_count(self) -> int:
        return len(self.content.split()) if self.content else 0


@dataclass
class Project:
    """Outcome-bearing multi-step commitment under an Area."""
    id: int
    title: str
    area: str = "Career"  # Health | Career | Learning | Relationships | Admin
    status: ProjectStatus = ProjectStatus.ACTIVE
    outcome: str = ""
    deadline: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    archived_at: Optional[str] = None
    uuid: str = field(default_factory=generate_uuid)
    actions: List[Action] = field(default_factory=list)


@dataclass
class Action:
    """Concrete, physical startable next action."""
    id: int
    title: str
    project_id: Optional[int] = None
    status: ActionStatus = ActionStatus.NEXT
    estimate_minutes: int = 30
    energy_level: EnergyLevel = EnergyLevel.MEDIUM
    context: str = "desk"  # desk | phone | errand | offline | deep
    due_date: Optional[str] = None
    scheduled_date: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    uuid: str = field(default_factory=generate_uuid)
    project_title: Optional[str] = None
    blocked_by: List[int] = field(default_factory=list)
    blocker_titles: List[str] = field(default_factory=list)

    @property
    def is_blocked(self) -> bool:
        return bool(self.blocked_by) or self.status == ActionStatus.WAITING


@dataclass
class ActionDependency:
    action_id: int
    blocked_by_action_id: int


@dataclass
class DailyPriority:
    """At most 3 outcome-bearing priority commitments per day."""
    id: int
    date: str
    action_id: int
    rank: int  # 1, 2, or 3
    committed_at: str = ""
    uuid: str = field(default_factory=generate_uuid)
    action: Optional[Action] = None


@dataclass
class TimeBlock:
    """Scheduled calendar focus block on the operational day timeline."""
    id: int
    date: str
    starts_at: str  # "09:00"
    ends_at: str    # "10:30"
    planned_minutes: int = 90
    actual_minutes: Optional[int] = None
    action_id: Optional[int] = None
    kind: BlockKind = BlockKind.DEEP_WORK
    status: BlockStatus = BlockStatus.PLANNED
    notes: Optional[str] = None
    uuid: str = field(default_factory=generate_uuid)
    action: Optional[Action] = None


@dataclass
class InboxItem:
    """Raw captured thought / distraction / loop before triage."""
    id: int
    content: str
    captured_at: str = ""
    source: str = "quick_capture"
    status: InboxStatus = InboxStatus.UNPROCESSED
    linked_project_id: Optional[int] = None
    converted_action_id: Optional[int] = None
    resolved_at: Optional[str] = None
    uuid: str = field(default_factory=generate_uuid)


@dataclass
class SyncState:
    status: SyncStateEnum = SyncStateEnum.LOCAL_ONLY
    last_synced_at: Optional[str] = None
    message: str = "local-only"
    unpushed_count: int = 0
