# dashboard/utils/config.py
# ─────────────────────────────────────────────────────────────
# Shim that re-exports the top-level utils.config module.
#
# Same rationale as dashboard/utils/logger.py: backend/services/
# analysis/__init__.py inserts dashboard/ onto sys.path BEFORE the
# project root, so `import utils` resolves to dashboard/utils/ —
# which historically did not have a config.py, breaking the 7+
# files that do `from utils.config import …`.
#
# Re-exports everything from the top-level utils.config module so
# the naming-collision is fully neutralised. Single source of truth
# remains utils/config.py.
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.append(_PROJECT_ROOT)

import importlib.util as _ilu

_TOP_CONFIG = os.path.join(_PROJECT_ROOT, "utils", "config.py")
_spec = _ilu.spec_from_file_location("_yiq_top_config", _TOP_CONFIG)
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# Re-export every public name from the top-level module.
for _name in dir(_mod):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_mod, _name)

__all__ = [n for n in dir(_mod) if not n.startswith("_")]
