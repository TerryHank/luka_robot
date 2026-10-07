from .interfaces import Behavior

class FollowBehavior(Behavior):
 def __init__(self,node):
  from nx_follow import FollowController
  from nx_follow_acquire import FollowAcquisition
  self.legacy_controller=FollowController(node)
  self.acquisition=FollowAcquisition(self.legacy_controller)
 def start(self,*args,**kwargs):return self.legacy_controller.start(*args,**kwargs)
 def cancel(self):
  self.acquisition.cancel()
  return self.legacy_controller.stop()
 def status(self):return self.legacy_controller.snapshot()
