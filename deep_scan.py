"""
Deep runtime-error scan for YieldIQ.
Checks for patterns that cause runtime (not syntax) errors.
"""
import os, re

BASE = r"C:\Users\vinit\Downloads\yieldiq_v6\yieldiq"

checks = [
    ("df_or_fallback",    re.compile(r'\)\s+or\s+(?:pd\.DataFrame|pd\.Series)\(')),
    ("df_truth_if",       re.compile(r'\bif\s+[\w\.]+_df\b(?!\s*is\b)(?!\s*not\b)(?!\s*==)(?!\s*!=)')),
    ("df_truth_not",      re.compile(r'\bnot\s+[\w\.]+_df\b(?!\s*is\b)')),
    ("backslash_fstring", re.compile(r"f'[^']*\\\\['\"][^']*'")),
    ("linux_strftime",    re.compile(r'%-[a-zA-Z]')),
    ("triple_ternary",    re.compile(r'(?:\"\"\"|\'\'\')[\s]*\)\s+if\s+')),
    ("bare_shelve_open",  re.compile(r'shelve\.open\(')),
]

findings = []
for root, dirs, files in os.walk(BASE):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for fname in files:
        if not fname.endswith(".py"):
            continue
        path = os.path.join(root, fname)
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for i, line in enumerate(fh, 1):
                for check_name, pat in checks:
                    if pat.search(line):
                        findings.append((check_name, fname, i, line.rstrip()))

if not findings:
    print("ALL CLEAR — no runtime error patterns found")
else:
    print(f"Found {len(findings)} potential issues:\n")
    for check_name, fname, lineno, line in findings:
        print(f"  [{check_name}] {fname}:{lineno}")
        print(f"    {line.strip()[:110]}")
    print()
