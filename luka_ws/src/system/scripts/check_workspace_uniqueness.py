#!/usr/bin/env python3
"""Enforce source package uniqueness and canonical functional ownership."""
from pathlib import Path
import ast
import collections
import json
import os
import sys
import xml.etree.ElementTree as ET

root=Path(__file__).resolve().parents[3]
src=root/'src'
skip={'.git','__pycache__','.pytest_cache','node_modules','venv','.venv','yolo26_venv','audio_venv',
      'build','install','log','site-packages'}
packages=collections.defaultdict(set)
errors=[]
for base,dirs,files in os.walk(src,followlinks=False):
    dirs[:]=[name for name in dirs if name not in skip]
    if 'package.xml' in files:
        p=Path(base)/'package.xml'
        try: name=ET.parse(p).getroot().findtext('name')
        except ET.ParseError as exc:
            errors.append(str(p)+': '+str(exc));continue
        if not name:errors.append('Missing package name: '+str(p));continue
        packages[name].add(str(p.resolve()))
for name,paths in packages.items():
    if len(paths)>1:errors.append('Duplicate package '+name+': '+', '.join(sorted(paths)))

registry=json.loads((src/'common/config/functional_owners.json').read_text())
for feature,record in registry['features'].items():
    for entry in record['canonical_sources']:
        if not (root/entry).exists():errors.append(feature+' missing owner '+entry)
for entry in registry['retired_sources']:
    if (root/entry).exists():errors.append('Retired implementation restored: '+entry)
for entry in registry['command_adapters']:
    p=root/entry
    tree=ast.parse(p.read_text())
    calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)]
    if any(node.func.attr=='create_publisher' for node in calls):
        errors.append('Command adapter must not create ROS publishers: '+entry)
for entry in registry['compatibility_launches']:
    tree=ast.parse((root/entry).read_text())
    if any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='Node' for n in ast.walk(tree)):
        errors.append('Compatibility launch must include canonical launch, not duplicate nodes: '+entry)
for alias,canonical in registry['shared_file_aliases'].items():
    if (root/alias).resolve() != (root/canonical).resolve():
        errors.append('Copied shared implementation: '+alias)
core=(src/'control/tros_person_following/src/person_following_node.cpp').read_text()
if 'async_cancel_all_goals' in core or 'cmd_vel_pub_' in core:
    errors.append('Official follower regained global cancellation or direct velocity output')
if errors:
    print('\n'.join(errors));raise SystemExit(1)
print(f'PASS: {len(packages)} physically unique package names (including ignored vendor sources); '
      f'{len(registry["features"])} functional owners and compatibility paths verified')
