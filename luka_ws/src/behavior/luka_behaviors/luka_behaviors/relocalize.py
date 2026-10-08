from .interfaces import Behavior

class RelocalizeBehavior(Behavior):
 def __init__(self,node,stop):
  from .relocalization import Relocalization
  self.legacy_controller=Relocalization(node,stop)
 def start(self,*args,**kwargs):return self.legacy_controller.start(*args,**kwargs)
 def cancel(self):return self.legacy_controller.stop_rotation()
 def status(self):return self.legacy_controller.snapshot()
