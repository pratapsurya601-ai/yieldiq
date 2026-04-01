"""
Fix ALL backslash-in-f-string errors across the YieldIQ codebase.
Handles:
  1. \'text\' inside f'...' strings  → "text"
  2. \"text\" inside f"..." expressions  → 'text'
  3. Nested f-strings with escaped quotes
  4. HTML event handlers with escaped quotes (onmouseover=\'...\')
Run from anywhere: python fix_fstrings.py
"""
import os, re

BASE = r"C:\Users\vinit\Downloads\yieldiq_v6\yieldiq"

# ---------- helpers ----------

def fix_escaped_single_in_fstring(line: str) -> str:
    """
    Replace \\'text\\' (escaped single quotes) inside f-strings with "text".
    Only touches lines that contain an f-string (f' or f\").
    """
    if not ("f'" in line or 'f"' in line):
        return line
    # Replace \\'...\\'  with  "..."
    return re.sub(r"\\'([^'\\]*)\\'", r'"\1"', line)


def fix_escaped_double_in_fstring(line: str) -> str:
    """
    Replace \\"text\\" (escaped double quotes inside f\"...\") with 'text'.
    e.g.  f\"{stage[\\"key\\"]}\"  ->  f\"{stage['key']}\"
    """
    if not ("f'" in line or 'f"' in line):
        return line
    # Replace \\"...\\"  with  '...'  only inside expression context
    return re.sub(r'\\"([^"\\]*)\\"', r"'\1'", line)


def fix_line(line: str) -> str:
    line = fix_escaped_single_in_fstring(line)
    line = fix_escaped_double_in_fstring(line)
    return line


# ---------- main ----------

total_files = 0
changed_files = []

for root, dirs, files in os.walk(BASE):
    # Skip __pycache__
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for fname in files:
        if not fname.endswith('.py'):
            continue
        path = os.path.join(root, fname)
        total_files += 1
        try:
            with open(path, encoding='utf-8', errors='ignore') as fh:
                lines = fh.readlines()
        except Exception as e:
            print(f"  SKIP (read error): {fname} — {e}")
            continue

        new_lines = [fix_line(l) for l in lines]
        if new_lines != lines:
            changed = [(i+1, old.rstrip(), new.rstrip())
                       for i, (old, new) in enumerate(zip(lines, new_lines))
                       if old != new]
            with open(path, 'w', encoding='utf-8') as fh:
                fh.writelines(new_lines)
            changed_files.append((fname, changed))

print(f"\nScanned {total_files} files — fixed {len(changed_files)} files\n")
for fname, changes in changed_files:
    print(f"  {fname}  ({len(changes)} line(s) changed)")
    for lineno, old, new in changes:
        print(f"    L{lineno}: {old.strip()[:80]}")
        print(f"         -> {new.strip()[:80]}")
    print()
