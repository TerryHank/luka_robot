from .navigate import NavigateBehavior
from .follow import FollowBehavior
from .relocalize import RelocalizeBehavior
from .stop import StopBehavior

class BehaviorRegistry:
 def __init__(self,node,send,stop):
  self.node=node
  self.navigate=NavigateBehavior(send,stop,lambda:{'active':node.nx_handle is not None,'message':node.nx_status})
  self.relocalize=RelocalizeBehavior(node,self.navigate.cancel)
  self.follow=None
  self.stop=StopBehavior(self,lambda:node.patrol_mission)
 def initialize_follow(self):
  self.follow=FollowBehavior(self.node)
