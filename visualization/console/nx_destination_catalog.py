"""Read confirmed customer POIs without exporting them into legacy map files."""
import math
PREFIX='customer_'
def customer_destinations(store,floor):
 doc=store.get('map:'+floor,{'pois':[]})['data'] or {}
 if doc.get('floor',floor)!=floor:return []
 rows=[]
 for p in doc.get('pois',[]):
  if not p.get('confirmed') or str(p.get('kind','')).startswith('elevator'):continue
  try:
   x,y=p['position'];yaw=p.get('yaw',0)
   if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in (x,y,yaw)):continue
   rows.append({'id':PREFIX+p['id'],'display_name':p['name'],'x':x,'y':y,'yaw':yaw,'floor_id':floor,'source':'customer'})
  except (KeyError,TypeError,ValueError):continue
 return rows
