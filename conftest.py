# conftest.py — repo-root pytest configuration.
#
# Exists solely to guarantee the repository root is first on
# `sys.path` during test collection. Without this, pytest's own
# rootdir detection + an unrelated `utils` package in global
# site-packages (present on some dev machines, surfaced 2026-04-23
# while landing `fix/moat-floor-strength-ssot`) can shadow the
# in-repo `utils/` package and break any test that imports a
# module which pulls in `utils.logger`.
#
# Kept deliberately minimal: no fixtures, no plugins, no assertions.
# If test infra grows, split fixtures into a separate conftest at
# `backend/tests/conftest.py` so this file stays purely about path.
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))

# Force the repo root to the FRONT of sys.path. Pytest's rootdir
# walk adds `dashboard/` as well (because it contains an
# `__init__.py`), and `dashboard/utils/__init__.py` shadows the
# real in-repo `utils/` package under that prefix — so any test
# that ends up importing `utils.logger` via `screener.*` crashes
# with `cannot import name 'logger' from 'utils'`. Putting the
# repo root first guarantees `utils` resolves to `yieldiq_v7/utils`.
if _ROOT in sys.path:
    sys.path.remove(_ROOT)
sys.path.insert(0, _ROOT)

# Pytest rootdir walk also prepends `dashboard/` to sys.path because
# it contains `__init__.py` + `utils/`, which shadows the in-repo
# `utils/logger.py` module. Proactively pin `utils` + `utils.logger`
# to the repo-root copies in `sys.modules` so subsequent
# `from utils.logger import get_logger` calls resolve correctly.
def _preload_repo_utils():
    import importlib.util

    # Drop any already-imported `utils*` that came from dashboard/.
    for _stale in list(sys.modules):
        if _stale == "utils" or _stale.startswith("utils."):
            _mod = sys.modules.get(_stale)
            _path = getattr(_mod, "__file__", "") or ""
            if "dashboard" in _path.replace("\\", "/"):
                del sys.modules[_stale]

    # Load the repo-root `utils` package + submodules explicitly.
    _utils_init = os.path.join(_ROOT, "utils", "__init__.py")
    _logger_py = os.path.join(_ROOT, "utils", "logger.py")
    if os.path.isfile(_utils_init) and os.path.isfile(_logger_py):
        _spec = importlib.util.spec_from_file_location(
            "utils", _utils_init,
            submodule_search_locations=[os.path.join(_ROOT, "utils")],
        )
        if _spec and _spec.loader:
            _mod = importlib.util.module_from_spec(_spec)
            sys.modules["utils"] = _mod
            _spec.loader.exec_module(_mod)
            _lspec = importlib.util.spec_from_file_location(
                "utils.logger", _logger_py,
            )
            if _lspec and _lspec.loader:
                _lmod = importlib.util.module_from_spec(_lspec)
                sys.modules["utils.logger"] = _lmod
                _lspec.loader.exec_module(_lmod)


_preload_repo_utils()
