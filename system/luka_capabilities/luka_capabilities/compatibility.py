"""Temporary dependency adapter for existing console API callers."""
from .dispatcher import CapabilityDispatcher


class LegacyBehaviorService:
 def __init__(self,node,send_nav):
  self.node=node;self.send_nav=send_nav
  self.follow=node.follow_controller;self.acquisition=node.follow_acquisition
  self.relocalize=node.relocalization
 def navigate(self,ident):return self.node.behaviors.navigate.start(ident) if hasattr(self.node,"behaviors") else self.send_nav(self.node,ident)
 def cancel_all(self):
  if hasattr(self.node,'behaviors'):return self.node.behaviors.stop.start()
  self.acquisition.cancel();self.follow.stop('已通过助手停止全部运动')
  result=self.node.patrol_mission.stop();self.relocalize.stop_rotation()
  return {'ok':True,'errors':[],'results':{'patrol':result}}


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
  from luka_mission.adapters import vision
  return vision(path,body)
 def voiceprint_status(self):
  from nx_voiceprint import VoiceprintStore
  return VoiceprintStore().status()


def execute(node,tool,args,source,catalog,send_nav,music):
 if hasattr(node,'capabilities'):return node.capabilities.execute(tool,args,source)
 return create_dispatcher(node,catalog,send_nav,music).execute(tool,args,source)


def create_dispatcher(node,catalog,send_nav,music):
 dispatcher=CapabilityDispatcher(node.patrol_mission,LegacyBehaviorService(node,send_nav),
                                 LegacyStatusService(node,catalog),music,node.product)
 return dispatcher
