"""Day-77 (2026-05-22): Python-side guard for the frontend vitest harness.

The repo already had a vitest config but no enforced lower-bound on
how many real component tests live in `frontend/__tests__/`. This
guard pins:

  1. `frontend/vitest.config.ts` exists.
  2. The setup file referenced by that config exists.
  3. At least three .test.tsx files live under `frontend/__tests__/`.
     (Day-77 shipped three new ones — VerdictChip, WatchlistButton,
     UpgradeActivationModal — on top of the existing batch. The
     floor of three keeps the harness from being deleted by a
     well-meaning cleanup.)
  4. `frontend/package.json` exposes a `test` script (the CI workflow
     in `.github/workflows/frontend-tests.yml` runs `npm test`).

Tier-3 follow-ups (frontend test coverage) should extend the floor
upward as more components get smoke tests.
"""
from __future__ import annotations

import json
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_FRONTEND = _ROOT / "frontend"


def test_vitest_config_exists() -> None:
    config = _FRONTEND / "vitest.config.ts"
    assert config.exists(), (
        f"vitest.config.ts must exist at {config} — the frontend test "
        "harness is wired through this file."
    )
    body = config.read_text(encoding="utf-8")
    assert "jsdom" in body, "vitest.config.ts must select the jsdom environment."
    assert "setupFiles" in body, (
        "vitest.config.ts must register a setupFiles entry so RTL "
        "matchers and afterEach cleanup are wired in."
    )


def test_vitest_setup_file_exists() -> None:
    # The config currently points at __tests__/setup.ts. If that name
    # ever changes, update both the config and this test together.
    setup = _FRONTEND / "__tests__" / "setup.ts"
    assert setup.exists(), (
        f"vitest setup file must exist at {setup} — referenced by "
        "vitest.config.ts setupFiles."
    )
    body = setup.read_text(encoding="utf-8")
    assert "@testing-library/jest-dom" in body, (
        "setup.ts must import @testing-library/jest-dom so toBeInTheDocument "
        "and friends are available in component tests."
    )


def test_at_least_three_tsx_tests_exist() -> None:
    tests_dir = _FRONTEND / "__tests__"
    assert tests_dir.is_dir(), f"{tests_dir} must exist"
    tsx_tests = sorted(p.name for p in tests_dir.glob("*.test.tsx"))
    assert len(tsx_tests) >= 3, (
        f"Expected at least 3 .test.tsx files under {tests_dir}, "
        f"found {len(tsx_tests)}: {tsx_tests}"
    )


def test_package_json_exposes_test_script() -> None:
    pkg = _FRONTEND / "package.json"
    assert pkg.exists(), f"{pkg} must exist"
    data = json.loads(pkg.read_text(encoding="utf-8"))
    scripts = data.get("scripts", {})
    assert "test" in scripts, (
        "frontend/package.json must declare a `test` script — the CI "
        "workflow runs `npm test` against this entry."
    )
    assert "vitest" in scripts["test"], (
        "The `test` script must invoke vitest (the harness Day-77 "
        f"pinned). Found: {scripts['test']!r}"
    )
