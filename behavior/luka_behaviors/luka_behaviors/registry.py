from .navigate import NavigateBehavior
from .follow import FollowBehavior
from .relocalize import RelocalizeBehavior
from .stop import StopBehavior

class BehaviorRegistry:
 def __init__(self,node,catalog,verified):
  from . import navigation_execution as navigation
  self.node=node
  navigation.initialize(node)
  self.navigate=NavigateBehavior(lambda *args,**kwargs:navigation.send_nav(node,*args,**kwargs),
                                lambda **kwargs:navigation.stop_nav(node,**kwargs),
                                lambda:{'active':node.nx_handle is not None,'message':node.nx_status})
  self.navigate.catalog=catalog;self.navigate.verified=verified
  self.relocalize=RelocalizeBehavior(node,self.navigate.cancel)
  self.follow=None
  self.stop=StopBehavior(self,lambda:node.patrol_mission)
 def initialize_follow(self):
  self.follow=FollowBehavior(self.node)
