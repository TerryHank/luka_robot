import time
import uuid

from .sources import SOURCES


class SourceLease:
    def __init__(self, clock=time.monotonic, timeout=.6):
        self.clock=clock;self.timeout=timeout;self.boot=uuid.uuid4().hex
        self.generation=0;self.source=None;self.owner=None;self.updated=0.
        self.manual=set();self.reason='no source lease'

    def invalidate(self, reason):
        self.source=self.owner=None;self.updated=0.;self.generation+=1;self.reason=reason

    def manual_input(self, source, active):
        if active:
            if source not in self.manual:self.invalidate('manual takeover: '+source)
            self.manual.add(source)
        else:self.manual.discard(source)

    def expire(self):
        if self.source and self.clock()-self.updated>self.timeout:
            self.invalidate('source lease expired')

    def request(self, command):
        self.expire()
        if command.get('boot')!=self.boot or type(command.get('generation')) is not int or command.get('generation')!=self.generation:
            raise ValueError('stale gateway boot/generation')
        source=command.get('source');owner=command.get('owner');mode=command.get('mode')
        if source not in SOURCES or not isinstance(owner,str) or not 1<=len(owner)<=80:
            raise ValueError('invalid source/owner')
        if mode=='acquire':
            if self.manual:raise ValueError('manual takeover active')
            if self.owner and self.owner!=owner:raise ValueError('another autonomous owner holds the lease')
            if self.source and self.source!=source:self.invalidate('explicit behavior source switch')
            self.source=source;self.owner=owner;self.updated=self.clock();self.reason=''
        elif mode=='renew':
            if self.manual or self.source!=source or self.owner!=owner:raise ValueError('lease owner/source mismatch')
            self.updated=self.clock()
        elif mode=='release':
            if self.owner!=owner or self.source!=source:raise ValueError('lease owner/source mismatch')
            self.invalidate('source released')
        else:raise ValueError('unknown lease operation')

    def permits(self, source):
        self.expire()
        return source in SOURCES and not self.manual and self.owner is not None and self.source==source

    def status(self):
        self.expire()
        return {'boot':self.boot,'generation':self.generation,'active_source':self.source,
                'owner':self.owner,'lease_age':self.clock()-self.updated if self.source else None,
                'blocked_reason':self.reason or ('manual takeover active' if self.manual else ''),
                'manual_sources':sorted(self.manual)}
