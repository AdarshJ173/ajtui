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
from typing import Optional


def generate_uuid() -> str:
    """Generate a clean UUIDv4 string."""
    return str(uuid.uuid4())


def current_iso_time() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


@dataclass
class Task:
    id: int
    title: str
    sort_order: int
    created_at: str = ""
    updated_at: str = ""
    uuid: str = field(default_factory=generate_uuid)
    active: bool = True


@dataclass
class Completion:
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


class SyncStateEnum(str, Enum):
    LIVE = "live"
    SYNCING = "syncing"
    OFFLINE = "offline"
    CONFLICT = "conflict"
    LOCAL_ONLY = "local_only"


@dataclass
class SyncState:
    status: SyncStateEnum = SyncStateEnum.LOCAL_ONLY
    last_synced_at: Optional[str] = None
    message: str = "local-only"
    unpushed_count: int = 0
