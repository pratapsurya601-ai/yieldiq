"""Formula audit — read-only sweep enforcing single-source-of-truth.

Walks the entire ``backend/`` tree (Python files only) and locates every
assignment, return, or keyword-argument that references one of the
canonical financial fields tracked below. For each hit we use the AST
to determine whether the value expression is a COMPUTATION (contains
arithmetic / call to a math helper) or a PASSTHROUGH (copies a value
from a dict subscript / attribute / variable without doing math on it).

A field is healthy if it has at most ONE computation site across the
entire backend. Multiple computations is a violation of the
single-source-of-truth invariant — the bug class that produced the
HCL fair-value regression.

Usage::

    python -m backend.audits.formula_audit

Exit code is ``0`` on PASS and ``1`` on FAIL. A markdown report is
written to ``reports/formula_audit_YYYYMMDD.md`` regardless of outcome.
"""
from __future__ import annotations

import ast
import datetime as _dt
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Canonical field names we audit. Synonyms / aliases that mean the same
# economic concept are grouped under a single canonical key so duplicate
# computations can't hide behind a rename.
TRACKED_FIELDS: dict[str, tuple[str, ...]] = {
    "margin_of_safety": ("margin_of_safety", "mos", "mos_pct"),
    "fair_value": ("fair_value", "fv", "intrinsic_value"),
    "bear_case": ("bear_case",),
    "base_case": ("base_case",),
    "bull_case": ("bull_case",),
    "roce": ("roce",),
    "ev_ebitda": ("ev_ebitda", "ev_to_ebitda"),
    "revenue_cagr_3y": ("revenue_cagr_3y", "rev_cagr_3y"),
    "revenue_cagr_5y": ("revenue_cagr_5y", "rev_cagr_5y"),
    "roe": ("roe", "return_on_equity"),
    "debt_to_equity": ("debt_to_equity", "de_ratio"),
}

# Reverse lookup: alias -> canonical name.
ALIAS_TO_CANONICAL: dict[str, str] = {
    alias: canonical
    for canonical, aliases in TRACKED_FIELDS.items()
    for alias in aliases
}

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"
REPORTS_DIR = REPO_ROOT / "reports"

# Subdirectories we deliberately skip — they are tests, caches, or
# generated artifacts and would create false positives.
SKIP_DIRS = {"__pycache__", "tests", "migrations", "audits"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Hit:
    canonical: str
    alias: str
    file: str  # relative to repo root, forward slashes
    line: int
    func: str
    kind: str  # "computation" or "passthrough"

    def sort_key(self) -> tuple:
        return (self.file, self.line)


@dataclass
class FieldReport:
    canonical: str
    computations: list[Hit] = field(default_factory=list)
    passthroughs: list[Hit] = field(default_factory=list)

    @property
    def violates(self) -> bool:
        return len(self.computations) > 1


# ---------------------------------------------------------------------------
# AST classification
# ---------------------------------------------------------------------------

# Nodes that, when present anywhere inside the value expression, mean the
# expression is doing math (computation) rather than just shuffling data.
_ARITH_OPS = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.MatMult,
)

# Names of helpers that, when called, count as performing math even if
# the surface expression looks like a passthrough (`x = compute_mos(...)`).
_MATH_CALL_HINTS = {
    "compute",
    "calc",
    "calculate",
    "derive",
    "_mos",
    "_fv",
    "_wacc",
    "discount",
    "dcf",
    "pv",
    "npv",
}


def _expr_is_computation(expr: ast.AST | None) -> bool:
    """Return True if *expr* contains arithmetic or a math-helper call."""
    if expr is None:
        return False
    for node in ast.walk(expr):
        if isinstance(node, ast.BinOp) and isinstance(node.op, _ARITH_OPS):
            return True
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            # `-x` alone isn't math; only flag if the operand isn't a bare name/attr.
            if not isinstance(node.operand, (ast.Name, ast.Attribute, ast.Subscript, ast.Constant)):
                return True
        if isinstance(node, ast.Call):
            name = _callable_name(node.func)
            if name and any(hint in name.lower() for hint in _MATH_CALL_HINTS):
                return True
    return False


def _callable_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _target_aliases(target: ast.AST) -> Iterable[str]:
    """Yield tracked alias names referenced as an assignment target."""
    if isinstance(target, ast.Name):
        if target.id in ALIAS_TO_CANONICAL:
            yield target.id
    elif isinstance(target, ast.Attribute):
        if target.attr in ALIAS_TO_CANONICAL:
            yield target.attr
    elif isinstance(target, ast.Subscript):
        # dict["fair_value"] = ...
        key = _subscript_key(target)
        if key and key in ALIAS_TO_CANONICAL:
            yield key
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            yield from _target_aliases(elt)


def _subscript_key(node: ast.Subscript) -> str | None:
    sl = node.slice
    if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
        return sl.value
    return None


# ---------------------------------------------------------------------------
# Visitor
# ---------------------------------------------------------------------------


class _Visitor(ast.NodeVisitor):
    def __init__(self, rel_path: str, hits: list[Hit]) -> None:
        self._path = rel_path
        self._hits = hits
        self._func_stack: list[str] = ["<module>"]

    # --- function tracking ---
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    # --- hits ---
    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        kind = "computation" if _expr_is_computation(node.value) else "passthrough"
        for tgt in node.targets:
            for alias in _target_aliases(tgt):
                self._record(alias, node.lineno, kind)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        kind = "computation" if _expr_is_computation(node.value) else "passthrough"
        for alias in _target_aliases(node.target):
            self._record(alias, node.lineno, kind)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:  # noqa: N802
        # `x += y` is always a computation.
        for alias in _target_aliases(node.target):
            self._record(alias, node.lineno, "computation")
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:  # noqa: N802
        # We don't know the field name from a bare return, but a Dict
        # literal at the return site does tell us.
        if isinstance(node.value, ast.Dict):
            for k, v in zip(node.value.keys, node.value.values):
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    if k.value in ALIAS_TO_CANONICAL:
                        kind = "computation" if _expr_is_computation(v) else "passthrough"
                        self._record(k.value, node.lineno, kind)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        # Keyword arguments: foo(fair_value=cmp * 1.2)
        for kw in node.keywords:
            if kw.arg and kw.arg in ALIAS_TO_CANONICAL:
                kind = "computation" if _expr_is_computation(kw.value) else "passthrough"
                self._record(kw.arg, node.lineno, kind)
        self.generic_visit(node)

    # --- internal ---
    def _record(self, alias: str, lineno: int, kind: str) -> None:
        self._hits.append(
            Hit(
                canonical=ALIAS_TO_CANONICAL[alias],
                alias=alias,
                file=self._path,
                line=lineno,
                func=self._func_stack[-1],
                kind=kind,
            )
        )


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------


def _iter_python_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        # in-place prune
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".py"):
                yield Path(dirpath) / fn


def collect_hits(root: Path = BACKEND_ROOT) -> list[Hit]:
    hits: list[Hit] = []
    for path in _iter_python_files(root):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError) as e:
            # Don't let one bad file kill the audit.
            print(f"  skipped {path}: {e}", file=sys.stderr)
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        _Visitor(rel, hits).visit(tree)
    return hits


def build_field_reports(hits: list[Hit]) -> dict[str, FieldReport]:
    reports: dict[str, FieldReport] = {
        canonical: FieldReport(canonical=canonical) for canonical in TRACKED_FIELDS
    }
    for h in hits:
        bucket = reports[h.canonical]
        if h.kind == "computation":
            bucket.computations.append(h)
        else:
            bucket.passthroughs.append(h)
    for r in reports.values():
        r.computations.sort(key=Hit.sort_key)
        r.passthroughs.sort(key=Hit.sort_key)
    return reports


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def _fmt_hit(h: Hit) -> str:
    return f"{h.file}:{h.line}  {h.func}()  [{h.alias}]"


def render_markdown(reports: dict[str, FieldReport], today: _dt.date) -> tuple[str, list[str]]:
    """Return ``(markdown, violations)`` where *violations* is the FAIL list."""
    lines: list[str] = [f"# Formula Audit {today.isoformat()}", ""]
    violations: list[str] = []

    for canonical, r in reports.items():
        lines.append(f"## {canonical}")
        lines.append("")
        lines.append(f"Computations (want: exactly 1):")
        if r.computations:
            for i, h in enumerate(r.computations):
                marker = "  - " + _fmt_hit(h)
                if i > 0:
                    marker += "   ⚠ DUPLICATE"
                lines.append(marker)
        else:
            lines.append("  - (none found)")
        lines.append("")
        lines.append(f"Passthroughs (count: {len(r.passthroughs)}):")
        for h in r.passthroughs:
            lines.append("  - " + _fmt_hit(h))
        lines.append("")
        if r.violates:
            n = len(r.computations)
            lines.append(f"STATUS: ⚠ {n} computations found — violates single-source rule")
            violations.append(f"{canonical} ({n} computations)")
        elif not r.computations:
            lines.append("STATUS: ℹ no computation found (passthrough-only — verify upstream)")
        else:
            lines.append("STATUS: ✓ single source")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("SUMMARY:")
    if violations:
        lines.append(f"FAIL  — {len(violations)} keys violate single-source rule:")
        for v in violations:
            lines.append(f"  - {v}")
    else:
        lines.append("PASS  — every key has ≤ 1 computation")
    lines.append("")
    return "\n".join(lines), violations


def write_report(markdown: str, today: _dt.date) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / f"formula_audit_{today.strftime('%Y%m%d')}.md"
    out.write_text(markdown, encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    today = _dt.date.today()
    hits = collect_hits()
    reports = build_field_reports(hits)
    markdown, violations = render_markdown(reports, today)
    out = write_report(markdown, today)

    print(f"Formula audit: {len(hits)} hits across {len(TRACKED_FIELDS)} tracked fields")
    print(f"Report written to {out.relative_to(REPO_ROOT).as_posix()}")
    if violations:
        print("FAIL — violations:")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("PASS — every key has ≤ 1 computation")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
