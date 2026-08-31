"""
lifeOS UI Package
"""

from lifeos.ui.capture_modal import CaptureModal
from lifeos.ui.close_modal import DailyCloseModal
from lifeos.ui.journal_screen import JournalScreen
from lifeos.ui.project_screen import ProjectScreen
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
    "CaptureModal",
    "DailyCloseModal",
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
