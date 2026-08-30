#!/usr/bin/env python3
"""
lifeOS Daily — State of the Art Routine & Momentum Tracker
==========================================================
Entrypoint proxy providing full backwards compatibility for `python daily.py`.
Automatically detects and uses local `.venv` if run under global python.
"""

import os
import sys
from pathlib import Path

# Auto-reexec inside project virtual environment if dependencies are missing
if __name__ == "__main__":
    venv_py = Path(__file__).parent / ".venv" / "bin" / "python"
    if venv_py.exists() and sys.executable != str(venv_py.resolve()):
        try:
            import textual
            import rich
        except ImportError:
            os.execv(str(venv_py), [str(venv_py)] + sys.argv)

from lifeos.app import DailyOS, main
from lifeos.core.models import Completion, JournalEntry, SyncState, SyncStateEnum, Task
from lifeos.db.local import DatabaseManager

if __name__ == "__main__":
    main()
