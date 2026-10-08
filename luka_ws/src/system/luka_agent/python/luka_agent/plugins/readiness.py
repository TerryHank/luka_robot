import json
from pathlib import Path
import socket


def vision_ready(context):
    cache = context.setdefault('_dependency_cache', {})
    if 'vision' not in cache:
        try:
            with socket.create_connection(('127.0.0.1', 8091), timeout=.25): pass
            cache['vision'] = {'ready': True}
        except OSError: cache['vision'] = {'ready': False, 'reason': 'vision_service_not_ready'}
    return cache['vision']


def music_provider_ready(context):
    try:
        path = Path('/home/sunrise/.config/luka_music/alapi.json')
        ready = not path.stat().st_mode & 0o077 and bool(json.loads(path.read_text()).get('token'))
        return {'ready': ready, 'reason': '' if ready else 'music_provider_not_configured'}
    except (OSError, ValueError): return {'ready': False, 'reason': 'music_provider_not_configured'}


def register(registry):
    # This module provides dependency checks, not another executable capability.
    pass
