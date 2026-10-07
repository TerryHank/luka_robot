import json
import threading
import time
import uuid

from rclpy.task import Future
from std_msgs.msg import String, Empty


class MotionLeaseClient:
    def __init__(self,node):
        self.node=node;self.owner=uuid.uuid4().hex;self.status={};self.received=0.
        self.desired=None;self.pending=None;self.cancelled_requests=set();self.lock=threading.RLock()
        self.publisher=node.create_publisher(String,'/luka/motion/lease',10)
        self.stop_pub=node.create_publisher(Empty,'/luka/motion/stop',10)
        node.create_subscription(String,'/luka/motion/status',self.observe,10)
        node.create_timer(.15,self.heartbeat)

    def observe(self,msg):
        try:state=json.loads(msg.data)
        except (TypeError,ValueError):return
        with self.lock:
            self.status=state;self.received=time.monotonic()
            ack=state.get('ack',{})
            if ack.get('request_id') in self.cancelled_requests and state.get('owner')==self.owner:
                self.send(state['active_source'],'release')
                self.cancelled_requests.discard(ack['request_id'])
            if self.pending and ack.get('request_id')==self.pending[0]:
                _,source,future,_=self.pending;self.pending=None
                if ack.get('accepted') and state.get('owner')==self.owner and state.get('active_source')==source:
                    self.desired=source;future.set_result(True)
                else:
                    self.desired=None;future.set_exception(ValueError(ack.get('error') or 'source lease not confirmed'))
            if self.desired and (state.get('owner')!=self.owner or state.get('active_source')!=self.desired):self.desired=None

    def send(self,source,mode,request_id=None):
        self.publisher.publish(String(data=json.dumps({'source':source,'owner':self.owner,'mode':mode,
            'generation':self.status.get('generation'),'boot':self.status.get('boot'),'request_id':request_id})))

    def request(self,source):
        with self.lock:
            future=Future()
            if time.monotonic()-self.received>.6 or not self.status:
                future.set_exception(ValueError('motion gateway status unavailable'));return future
            if self.pending:
                future.set_exception(ValueError('source lease request already pending'));return future
            token=uuid.uuid4().hex;self.pending=(token,source,future,time.monotonic())
            self.send(source,'acquire',token)
            return future

    def acquire(self,source):
        future=self.request(source);done=threading.Event();future.add_done_callback(lambda _:done.set())
        if not done.wait(2):
            self.release();raise ValueError('source lease acquisition timed out')
        return future.result()

    def valid(self,source):
        with self.lock:return (self.desired==source and time.monotonic()-self.received<=.6 and
                              self.status.get('owner')==self.owner and self.status.get('active_source')==source)

    def release(self):
        with self.lock:
            source=self.desired
            self.desired=None
            if source:self.send(source,'release')
            if self.pending:
                token,_,future,_=self.pending;self.pending=None
                self.cancelled_requests.add(token)
                if not future.done():future.set_exception(ValueError('source lease request cancelled'))

    def stop(self):
        self.release();self.stop_pub.publish(Empty())

    def heartbeat(self):
        with self.lock:
            if self.pending and time.monotonic()-self.pending[3]>1.5:
                self.release();return
            if self.desired:
                if self.valid(self.desired):self.send(self.desired,'renew')
                else:self.release()
