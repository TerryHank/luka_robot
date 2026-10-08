"""Internet reachability is independent of AIUI auth/service readiness."""
import socket
import threading
import time


class Connectivity:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.value = 'unknown'
        self.checked_at = None
        self.failures = 0

    def update(self, reachable):
        self.checked_at = self.clock()
        if reachable:
            self.value = 'online'; self.failures = 0
        else:
            self.failures += 1
            if self.failures >= 2:
                self.value = 'offline'

    def state(self):
        if self.checked_at is None or self.clock() - self.checked_at > 10:
            return 'unknown'
        return self.value


class NetworkMonitor(Connectivity):
    def __init__(self, stop):
        super().__init__()
        self.stop = stop
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def probe(self):
        for host in ('aiui.xf-yun.com', 'www.baidu.com'):
            try:
                with socket.create_connection((host, 443), timeout=1.5):
                    return True
            except OSError:
                continue
        return False

    def run(self):
        while not self.stop.is_set():
            self.update(self.probe())
            self.stop.wait(2)
