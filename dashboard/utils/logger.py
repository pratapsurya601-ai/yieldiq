# dashboard/utils/logger.py
# ─────────────────────────────────────────────────────────────
# Shim that re-exports get_logger from the top-level utils.logger.
#
# Why this exists: backend/services/analysis/__init__.py inserts
# `dashboard/` onto sys.path so `from utils.X import …` (used by
# 23 files in screener/, models/, data/) resolves. But `dashboard/`
# is inserted BEFORE the project root, so `import utils` picks up
# `dashboard/utils/` first — which historically did not have a
# logger.py, breaking `from utils.logger import get_logger` in
# slim envs like the hex_history backfill GH Actions runner.
#
# Re-exporting from the top-level keeps a single implementation
# while letting both import paths work.
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make sure the project root is importable so the top-level
# `utils` package can be loaded by absolute path.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.append(_PROJECT_ROOT)

# Load top-level utils/logger.py directly to avoid the package-name
# collision (`utils` has already been bound to dashboard/utils).
import importlib.util as _ilu

_TOP_LOGGER = os.path.join(_PROJECT_ROOT, "utils", "logger.py")
_spec = _ilu.spec_from_file_location("_yiq_top_logger", _TOP_LOGGER)
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

get_logger = _mod.get_logger

__all__ = ["get_logger"]
