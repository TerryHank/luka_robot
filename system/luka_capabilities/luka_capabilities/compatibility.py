"""Temporary dependency adapter for existing console API callers."""
from .dispatcher import CapabilityDispatcher


class LegacyBehaviorService:
 def __init__(self,node,send_nav):
  self.node=node;self.send_nav=send_nav
  self.follow=node.follow_controller;self.acquisition=node.follow_acquisition
  self.relocalize=node.relocalization
 def navigate(self,ident):return self.send_nav(self.node,ident)


class LegacyStatusService:
 def __init__(self,node,catalog):self.node=node;self.catalog=catalog
 @property
 def navigation_active(self):return self.node.nx_handle is not None
 @property
 def navigation_lock(self):return self.node.nx_lock
 @property
 def functions(self):return self.node.function_start
 def destinations(self):return self.catalog(self.node)
 def set_voice_volume(self,direction):
  from std_msgs.msg import String
  self.node.nx_voice_pub.publish(String(data='volume_'+direction))
 def vision(self,path,body=None):
  from nx_patrol_mission import vision
  return vision(path,body)
 def voiceprint_status(self):
  from nx_voiceprint import VoiceprintStore
  return VoiceprintStore().status()


def execute(node,tool,args,source,catalog,send_nav,music):
 dispatcher=CapabilityDispatcher(node.patrol_mission,LegacyBehaviorService(node,send_nav),
                                 LegacyStatusService(node,catalog),music,node.product)
 return dispatcher.execute(tool,args,source)
