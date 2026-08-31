"""
lifeOS UI Package
"""

from lifeos.ui.ai_modal import AIDraftModal
from lifeos.ui.capture_modal import CaptureModal
from lifeos.ui.close_modal import DailyCloseModal
from lifeos.ui.command_palette import CommandPaletteModal
from lifeos.ui.focus_cockpit import FocusCockpitModal
from lifeos.ui.help_modal import HelpModal
from lifeos.ui.journal_screen import JournalScreen
from lifeos.ui.missed_block_modal import MissedBlockModal
from lifeos.ui.plan_screen import PlanScreen
from lifeos.ui.project_screen import ProjectScreen
from lifeos.ui.review_screen import ReviewScreen
from lifeos.ui.schedule_modal import ScheduleBlockModal
from lifeos.ui.themes import Theme, get_theme, resolve_startup_theme
from lifeos.ui.today_screen import (
    CaptureCardView,
    CommitmentsCardView,
    NowCardView,
    RoutinesCompactCardView,
    TodaysThreeView,
)
from lifeos.ui.widgets import (
    BootOverlay,
    ConfirmModal,
    HeaderBar,
    HeroBanner,
    KeyChipBar,
    MomentumDock,
    MonthCalendarView,
    TaskListView,
    TextInputModal,
    ToastRail,
)

__all__ = [
    "JournalScreen",
    "ProjectScreen",
    "PlanScreen",
    "ReviewScreen",
    "FocusCockpitModal",
    "MissedBlockModal",
    "ScheduleBlockModal",
    "CaptureModal",
    "DailyCloseModal",
    "CommandPaletteModal",
    "HelpModal",
    "AIDraftModal",
    "NowCardView",
    "TodaysThreeView",
    "CommitmentsCardView",
    "RoutinesCompactCardView",
    "CaptureCardView",
    "HeaderBar",
    "HeroBanner",
    "TaskListView",
    "MonthCalendarView",
    "MomentumDock",
    "ToastRail",
    "KeyChipBar",
    "BootOverlay",
    "TextInputModal",
    "ConfirmModal",
    "Theme",
    "get_theme",
    "resolve_startup_theme",
]
