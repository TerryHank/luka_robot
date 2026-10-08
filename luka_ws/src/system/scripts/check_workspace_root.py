#!/usr/bin/env python3
"""Reject source/data directories and compatibility links at workspace root."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[3]
allowed_directories = {'src', 'build', 'install', 'log'}
violations = set()
for path in root.iterdir():
    if path.is_symlink():
        violations.add(path.name + ' (root symlink)')
    elif path.is_dir() and not path.name.startswith('.') and path.name not in allowed_directories:
        violations.add(path.name + '/ (must be under src/ or outside the workspace)')
entries = subprocess.check_output(
    ['git', '-C', str(root), 'ls-files', '--stage', '-z']
).decode().split('\0')
for entry in entries:
    if not entry:
        continue
    metadata, name = entry.split('\t', 1)
    if metadata.startswith('120000 ') and '/' not in name:
        violations.add(name + ' (tracked root symlink)')
    if '/' in name:
        top = name.split('/', 1)[0]
        if not top.startswith('.') and top not in allowed_directories:
            violations.add(top + '/ (tracked outside src/)')
if violations:
    print('Workspace architecture violation:', file=sys.stderr)
    for item in sorted(violations):
        print(item, file=sys.stderr)
    sys.exit(1)
print('PASS: source domains are under src/; workspace root has no compatibility links')
