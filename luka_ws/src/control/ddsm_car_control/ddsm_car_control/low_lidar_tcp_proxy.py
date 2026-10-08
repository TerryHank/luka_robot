#!/usr/bin/env python3
import argparse
import select
import signal
import socket
import time


RUNNING = True


def _stop(_signum, _frame):
    global RUNNING
    RUNNING = False


def _relay(client, upstream):
    sockets = (client, upstream)
    while RUNNING:
        readable, _, _ = select.select(sockets, (), (), 1.0)
        for source in readable:
            data = source.recv(65536)
            if not data:
                return
            target = upstream if source is client else client
            target.sendall(data)


def _connect_upstream(interface, source_ip, target_ip, target_port):
    upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    upstream.settimeout(3.0)
    upstream.setsockopt(
        socket.SOL_SOCKET, socket.SO_BINDTODEVICE, interface.encode() + b'\0'
    )
    upstream.bind((source_ip, 0))
    upstream.connect((target_ip, target_port))
    upstream.settimeout(None)
    return upstream


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument('--interface', default='eth0')
    parser.add_argument('--source-ip', default='192.168.11.11')
    parser.add_argument('--target-ip', default='192.168.11.2')
    parser.add_argument('--target-port', type=int, default=8089)
    parser.add_argument('--listen-port', type=int, default=18089)
    args, _ = parser.parse_known_args()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', args.listen_port))
    listener.listen(2)
    listener.settimeout(1.0)
    print(
        f'low lidar proxy 127.0.0.1:{args.listen_port} -> '
        f'{args.interface}/{args.source_ip} -> {args.target_ip}:{args.target_port}',
        flush=True,
    )

    while RUNNING:
        try:
            client, _ = listener.accept()
        except socket.timeout:
            continue
        try:
            upstream = _connect_upstream(
                args.interface, args.source_ip, args.target_ip, args.target_port
            )
            print('low lidar proxy connected', flush=True)
            with client, upstream:
                _relay(client, upstream)
        except (OSError, ConnectionError) as exc:
            print(f'low lidar proxy reconnect: {exc}', flush=True)
            client.close()
            time.sleep(1.0)
    listener.close()


if __name__ == '__main__':
    main()
