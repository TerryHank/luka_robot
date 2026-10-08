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

    local = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    local.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    local.bind(('127.0.0.1', args.listen_port))

    upstream = None
    while RUNNING:
        candidate=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        try:
            candidate.setsockopt(socket.SOL_SOCKET,socket.SO_BINDTODEVICE,args.interface.encode()+b'\0')
            candidate.bind((args.source_ip,0))
            candidate.connect((args.target_ip,args.target_port))
            upstream=candidate;break
        except OSError as exc:
            candidate.close()
            print(f'Waiting for lidar interface {args.interface}/{args.source_ip}: {exc}',flush=True)
            for _ in range(25):
                if not RUNNING:break
                time.sleep(.2)
    if upstream is None:
        local.close();return

    print(
        f'low lidar UDP proxy 127.0.0.1:{args.listen_port} -> '
        f'{args.interface}/{args.source_ip} -> {args.target_ip}:{args.target_port}',
        flush=True,
    )
    client_address = None
    while RUNNING:
        readable, _, _ = select.select((local, upstream), (), (), 1.0)
        for source in readable:
            if source is local:
                data, client_address = local.recvfrom(65535)
                if data:
                    upstream.send(data)
            else:
                data = upstream.recv(65535)
                if data and client_address is not None:
                    local.sendto(data, client_address)

    local.close()
    upstream.close()


if __name__ == '__main__':
    main()
