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
  self.stop=StopBehavior(self,lambda:node.patrol_mission)
  node.create_timer(.1,self.motion_watchdog)
 def initialize_follow(self):
  self.follow=FollowBehavior(self.node)
 def motion_watchdog(self):
  motion=self.node.motion
  if self.node.nx_handle is not None and not motion.valid('nav'):self.navigate.cancel(wait_for_gate=False)
  if self.follow and self.follow.legacy_controller.enabled:
   controller=self.follow.legacy_controller
   if not controller.nav_mode and not controller.detour.active and not motion.valid('follow'):self.follow.cancel()
  if self.relocalize.legacy_controller.running and motion.desired=='relocalize' and not motion.valid('relocalize'):
   self.relocalize.cancel()
