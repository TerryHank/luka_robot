from .navigate import NavigateBehavior
from .follow import FollowBehavior
from .relocalize import RelocalizeBehavior
from .stop import StopBehavior

class BehaviorRegistry:
 def __init__(self,node,catalog,verified):
  from . import navigation_execution as navigation
  from luka_motion_gateway.client import MotionLeaseClient
  node.motion=MotionLeaseClient(node)
  self.node=node
  navigation.initialize(node)
  self.navigate=NavigateBehavior(lambda *args,**kwargs:navigation.send_nav(node,*args,**kwargs),
                                lambda **kwargs:navigation.stop_nav(node,**kwargs),
                                lambda:{'active':node.nx_handle is not None,'message':node.nx_status})
  self.navigate.catalog=catalog;self.navigate.verified=verified
  self.relocalize=RelocalizeBehavior(node,self.navigate.cancel)
  self.follow=None
  self.recovery=None
  self.stop=StopBehavior(self,lambda:node.patrol_mission)
  node.motion.on_revoked=self.motion_revoked
  node.create_timer(.1,self.motion_watchdog)
 def initialize_follow(self):
  self.follow=FollowBehavior(self.node)
 def initialize_recovery(self):
  from .recovery import EscapeRecovery
  self.recovery=EscapeRecovery(self.node)
  return self.recovery
 def motion_revoked(self,source):
  import threading
  self.node.nx_nav_cancel_requested=True
  self.relocalize.legacy_controller.cancel.set()
  # Do not hold a ROS callback group while waiting on legacy behavior locks.
  def cancel_owned_behaviors():
   self.navigate.cancel(wait_for_gate=False)
   if self.follow:self.follow.cancel()
   if self.recovery:self.recovery.cancel('自主运动租约已失效')
  threading.Thread(target=cancel_owned_behaviors,daemon=True).start()
 def motion_watchdog(self):
  motion=self.node.motion
  if self.node.nx_handle is not None and not motion.valid('nav'):self.navigate.cancel(wait_for_gate=False)
  if self.follow and self.follow.legacy_controller.enabled:
   controller=self.follow.legacy_controller
   if not controller.nav_mode and not controller.detour.active and not motion.valid('follow'):self.follow.cancel()
  if self.relocalize.legacy_controller.running and motion.desired=='relocalize' and not motion.valid('relocalize'):
   self.relocalize.cancel()
