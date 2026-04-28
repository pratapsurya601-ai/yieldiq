#!/usr/bin/env python3
"""Declare fix status on issues/PRs labelled `fix-pending-validation`.

Implements CLAUDE.md rule #3: a bug is not "fixed" until 7 consecutive
nightly canary runs are clean AND the fix has been on `main` for at
least 7 days.

This script is meant to be run from a scheduled GH Actions job (or
manually) with `GH_TOKEN` available in the environment so that
`gh issue comment` / `gh pr comment` succeed.

Usage:
    python scripts/declare_fix_status.py [--dry-run] [--repo owner/name]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
from typing import Iterable


HISTORY_PATH = pathlib.Path("docs/canary_history.jsonl")
LABEL = "fix-pending-validation"
DECLARED_MARKER = "<!-- discipline-rule-3-declared -->"
PROGRESS_MARKER = "<!-- discipline-rule-3-progress -->"


def compute_streak(history_path: pathlib.Path = HISTORY_PATH) -> int:
    """Return the count of consecutive trailing clean canary runs."""
    if not history_path.is_file():
        return 0
    streak = 0
    for line in reversed(history_path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            break
        if entry.get("clean"):
            streak += 1
        else:
            break
    return streak


def days_on_main(merge_iso: str) -> float:
    """Return days elapsed since `merge_iso` (UTC ISO-8601)."""
    if not merge_iso:
        return 0.0
    merge_dt = dt.datetime.fromisoformat(merge_iso.replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)
    return (now - merge_dt).total_seconds() / 86400.0


def gh_json(args: list[str]) -> object:
    """Call `gh` and return parsed JSON output."""
    out = subprocess.check_output(["gh", *args], text=True)
    return json.loads(out) if out.strip() else None


def list_pending_items(repo: str | None) -> Iterable[dict]:
    """Yield {kind, number, mergedAt} for open issues/PRs with the label."""
    repo_args = ["--repo", repo] if repo else []
    pr_args = ["pr", "list", "--state", "all", "--label", LABEL,
               "--json", "number,mergedAt,state,url",
               "--limit", "200", *repo_args]
    issue_args = ["issue", "list", "--state", "open", "--label", LABEL,
                  "--json", "number,createdAt,url",
                  "--limit", "200", *repo_args]
    for pr in (gh_json(pr_args) or []):
        yield {
            "kind": "pr",
            "number": pr["number"],
            "since": pr.get("mergedAt") or "",
            "state": pr.get("state"),
            "url": pr.get("url"),
        }
    for iss in (gh_json(issue_args) or []):
        yield {
            "kind": "issue",
            "number": iss["number"],
            "since": iss.get("createdAt") or "",
            "state": "OPEN",
            "url": iss.get("url"),
        }


def post_comment(kind: str, number: int, body: str,
                 repo: str | None, dry_run: bool) -> None:
    repo_args = ["--repo", repo] if repo else []
    cmd = ["gh", kind, "comment", str(number), "--body", body, *repo_args]
    if dry_run:
        print("[dry-run]", " ".join(cmd))
        return
    subprocess.check_call(cmd)


def build_message(streak: int, days: float, *, declared: bool) -> str:
    if declared:
        return (f"{DECLARED_MARKER}\n"
                f"Per CLAUDE.md rule #3, this fix is now declared **FIXED**.\n\n"
                f"- Canary streak: **{streak}/7** consecutive clean nights.\n"
                f"- Days on `main`: **{days:.1f}** (>= 7 required).\n\n"
                f"Removing the `fix-pending-validation` label is safe.")
    return (f"{PROGRESS_MARKER}\n"
            f"Streak: **{streak}/7** consecutive clean canary nights.\n"
            f"Days on `main`: **{days:.1f}/7**.\n\n"
            f"Per CLAUDE.md rule #3, both gates must clear before this "
            f"fix can be declared FIXED.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY") or None)
    p.add_argument("--history", default=str(HISTORY_PATH))
    args = p.parse_args(argv)

    streak = compute_streak(pathlib.Path(args.history))
    print(f"Current canary streak: {streak}/7 consecutive clean nights")

    items = list(list_pending_items(args.repo))
    if not items:
        print(f"No open items with label '{LABEL}'.")
        return 0

    for item in items:
        days = days_on_main(item["since"]) if item["since"] else 0.0
        declared = streak >= 7 and days >= 7.0
        body = build_message(streak, days, declared=declared)
        print(f"- {item['kind']}#{item['number']}: streak={streak} "
              f"days={days:.1f} declared={declared}")
        post_comment(item["kind"], item["number"], body,
                     args.repo, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
