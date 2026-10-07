#!/usr/bin/env python3
"""Reject root-level compatibility symlinks in both Git and the live workspace."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
entries = subprocess.check_output(
    ['git', '-C', str(root), 'ls-files', '--stage', '-z']
).decode().split('\0')
shortcuts = {p.name for p in root.iterdir() if p.is_symlink()}
for entry in entries:
    if not entry:
        continue
    metadata, name = entry.split('\t', 1)
    if metadata.startswith('120000 ') and '/' not in name:
        shortcuts.add(name)
if shortcuts:
    print('Root shortcuts must use their categorized target paths:', file=sys.stderr)
    for name in sorted(shortcuts):
        print(name, file=sys.stderr)
    sys.exit(1)
print('PASS: workspace root contains no compatibility symlinks')
