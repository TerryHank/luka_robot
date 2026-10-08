import math
import time

from .lease import SourceLease


class MotionArbiter:
    def __init__(self, clock=time.monotonic, command_timeout=.25):
        self.clock=clock;self.command_timeout=command_timeout
        self.lease=SourceLease(clock);self.command=None;self.command_at=0.;self.command_generation=-1

    def receive(self, source, velocity):
        if len(velocity)!=6 or not all(math.isfinite(v) for v in velocity):
            self.command=None;return False
        if not self.lease.permits(source):return False
        self.command=list(velocity);self.command_at=self.clock();self.command_generation=self.lease.generation
        return True

    def output(self):
        if (not self.lease.permits(self.lease.source) or self.command is None or
                self.command_generation!=self.lease.generation or self.clock()-self.command_at>self.command_timeout):
            return [0.]*6
        return list(self.command)

    def stop(self, reason='explicit stop'):
        self.command=None;self.lease.invalidate(reason)

    def status(self):
        state=self.lease.status()
        state['last_command_age']=self.clock()-self.command_at if self.command is not None else None
        if self.lease.source and self.output()==[0.]*6 and state['last_command_age'] is not None and state['last_command_age']>self.command_timeout:
            state['blocked_reason']='velocity command expired'
        return state
