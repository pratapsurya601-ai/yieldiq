# backend/__init__.py — ensure project root is on sys.path
# This MUST run before any other backend module imports existing code.
import sys
import os
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
_DASHBOARD_ROOT = os.path.join(_PROJECT_ROOT, "dashboard")

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, _DASHBOARD_ROOT)