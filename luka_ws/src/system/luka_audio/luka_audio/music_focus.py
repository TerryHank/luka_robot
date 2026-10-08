"""Coordinate speech with the existing music owner through its local IPC."""
import json
from pathlib import Path
import socket

SOCKET = '/home/sunrise/luka_data/runtime/music/player.sock'


def epoch(field):
    try: return json.loads(Path(SOCKET).with_name('focus_epoch.json').read_text()).get(field, 0)
    except (OSError, ValueError): return 0


def command(*args):
    if not Path(SOCKET).exists(): return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(.2); connection.connect(SOCKET)
            connection.sendall((json.dumps({'command': list(args), 'request_id': 113}) + '\n').encode())
            stream = connection.makefile('rb')
            for _ in range(10):
                reply = json.loads(stream.readline(65536))
                if reply.get('request_id') == 113: return reply.get('data')
    except (OSError, ValueError): return None


def pause():
    if command('get_property', 'pause') is False:
        ticket = {'epoch': epoch('transport'), 'path': command('get_property', 'path')}
        command('set_property', 'pause', True)
        return ticket


def resume(ticket):
    if ticket and ticket['epoch'] == epoch('transport') and ticket['path'] == command('get_property', 'path'):
        if command('get_property', 'pause') is True: command('set_property', 'pause', False)


def duck():
    volume = command('get_property', 'volume')
    if isinstance(volume, (int, float)) and volume > 8:
        command('set_property', 'volume', 8)
        return {'volume': volume, 'epoch': epoch('volume')}


def restore(ticket):
    if ticket is not None and ticket['epoch'] == epoch('volume') and command('get_property', 'volume') == 8:
        command('set_property', 'volume', ticket['volume'])
