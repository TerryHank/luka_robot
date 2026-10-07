from .interfaces import Behavior

class NavigateBehavior(Behavior):
 def __init__(self,send,stop,status):self.send=send;self.stop=stop;self.read_status=status
 def start(self,*args,**kwargs):return self.send(*args,**kwargs)
 def cancel(self,**kwargs):return self.stop(**kwargs)
 def status(self):return self.read_status()
