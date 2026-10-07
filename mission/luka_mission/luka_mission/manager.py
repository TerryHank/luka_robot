from .patrol import PatrolMission

class MissionManager:
 def __init__(self,node,behaviors,speak):
  self.patrol=PatrolMission(node,speak=speak,behaviors=behaviors)
 def status(self):return self.patrol.snapshot()
 def cancel(self):return self.patrol.stop()
