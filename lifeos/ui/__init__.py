"""
lifeOS UI Package
"""

from lifeos.ui.ai_modal import AIDraftModal
from lifeos.ui.ai_screen import AIScreen, AIView
from lifeos.ui.capture_modal import CaptureModal
from lifeos.ui.close_modal import DailyCloseModal
from lifeos.ui.command_palette import CommandPaletteModal
from lifeos.ui.focus_cockpit import FocusCockpitModal
from lifeos.ui.help_modal import HelpModal
from lifeos.ui.journal_screen import JournalScreen
from lifeos.ui.missed_block_modal import MissedBlockModal
from lifeos.ui.plan_screen import PlanScreen, PlanView
from lifeos.ui.project_screen import ProjectScreen, ProjectView
from lifeos.ui.review_screen import ReviewScreen, ReviewView
from lifeos.ui.schedule_modal import ScheduleBlockModal
from lifeos.ui.themes import Theme, get_theme, resolve_startup_theme
from lifeos.ui.today_screen import (
    AIBriefCardView,
    CaptureCardView,
    CommitmentsCardView,
    NowCardView,
    PatternsCardView,
    PlanDayTimelineView,
    RoutinesAndHeatmapView,
    RoutinesCompactCardView,
    TodayScreen,
    TodayTitleView,
    TodayView,
    TodaysThreeView,
)
from lifeos.ui.widgets import (
    BootOverlay,
    BottomStatusBar,
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
    "ProjectView",
    "PlanScreen",
    "PlanView",
    "ReviewScreen",
    "ReviewView",
    "AIScreen",
    "AIView",
    "FocusCockpitModal",
    "MissedBlockModal",
    "ScheduleBlockModal",
    "CaptureModal",
    "DailyCloseModal",
    "CommandPaletteModal",
    "HelpModal",
    "AIDraftModal",
    "TodayScreen",
    "TodayView",
    "TodayTitleView",
    "NowCardView",
    "TodaysThreeView",
    "CommitmentsCardView",
    "RoutinesCompactCardView",
    "CaptureCardView",
    "PlanDayTimelineView",
    "RoutinesAndHeatmapView",
    "AIBriefCardView",
    "PatternsCardView",
    "HeaderBar",
    "BottomStatusBar",
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

