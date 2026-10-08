from abc import ABC, abstractmethod

class Behavior(ABC):
 @abstractmethod
 def start(self,*args,**kwargs):raise NotImplementedError
 @abstractmethod
 def cancel(self):raise NotImplementedError
 @abstractmethod
 def status(self):raise NotImplementedError
