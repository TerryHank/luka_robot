"""Geometry-derived room/door proposals; known labels remain traceable hints."""
import cv2,numpy as np,math,hashlib,json
from scipy import ndimage

def propose(image,info,known):
    gray=cv2.imdecode(np.frombuffer(image,np.uint8),cv2.IMREAD_GRAYSCALE)
    if gray is None:raise ValueError('地图图像无法读取')
    free=gray>240;distance=cv2.distanceTransform(free.astype('uint8'),cv2.DIST_L2,5)*info['resolution']
    labels,count=ndimage.label(distance>.48)
    sizes=np.bincount(labels.ravel());markers=np.zeros_like(labels,dtype='int32');seed_names={};seed=1
    def world(px,py):
        lx=px*info['resolution'];ly=(info['height']-py)*info['resolution'];a=info.get('origin_yaw',0)
        return [round(info['origin_x']+math.cos(a)*lx-math.sin(a)*ly,3),round(info['origin_y']+math.sin(a)*lx+math.cos(a)*ly,3)]
    def pixel(x,y):
        dx=x-info['origin_x'];dy=y-info['origin_y'];a=-info.get('origin_yaw',0)
        return round((math.cos(a)*dx-math.sin(a)*dy)/info['resolution']),round(info['height']-(math.sin(a)*dx+math.cos(a)*dy)/info['resolution'])
    for label in sorted(range(1,count+1),key=lambda i:sizes[i],reverse=True)[:40]:
        if sizes[label]*info['resolution']**2<.5:continue
        seed+=1;markers[labels==label]=seed
    for poi in known:
        name=poi.get('display_name','')
        if name not in ('厨房','卧室','浴室','客厅','餐厅','书房','卫生间','会议室','办公室'):continue
        x,y=pixel(poi['x'],poi['y'])
        if not (0<=x<gray.shape[1] and 0<=y<gray.shape[0]):continue
        window=distance[max(0,y-12):y+13,max(0,x-12):x+13]
        if not window.size or window.max()<.25:continue
        yy,xx=np.unravel_index(window.argmax(),window.shape);y=max(0,y-12)+yy;x=max(0,x-12)+xx
        value=int(markers[y,x])
        if value<2 or value in seed_names:
            seed+=1;value=seed;cv2.circle(markers,(int(x),int(y)),2,value,-1)
        seed_names[value]=name
    if seed==1:raise ValueError('地图中没有足够的可通行空间，请先完成建图')
    markers[~free]=1
    terrain=np.clip(255-distance*130,0,255).astype('uint8')
    grown=cv2.watershed(cv2.cvtColor(terrain,cv2.COLOR_GRAY2BGR),markers)
    grown[~free]=0;rooms=[];pois=[];centers={}
    for ident in range(2,seed+1):
        mask=(grown==ident).astype('uint8')
        if mask.sum()*info['resolution']**2<1:continue
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        if not contours:continue
        contour=max(contours,key=cv2.contourArea);poly=cv2.approxPolyDP(contour,max(1,.10/info['resolution']),True)[:,0,:]
        if not 3<=len(poly)<=100:continue
        room_id='room_'+str(ident);name=seed_names.get(ident,'空间 '+str(len(rooms)+1).zfill(2))
        rooms.append(dict(id=room_id,name=name,polygon=[world(int(x),int(y)) for x,y in poly],confirmed=False,source='existing_waypoint_hint' if ident in seed_names else 'map_geometry',area_m2=round(float(mask.sum())*info['resolution']**2,1)))
        local=distance*mask;y,x=np.unravel_index(local.argmax(),local.shape);centers[ident]=(x,y)
        if local[y,x]>=.32:pois.append(dict(id='entry_'+str(ident),name=name+'到达点',kind='room_entry',position=world(x,y),yaw=0.,confirmed=False,room_id=room_id,source='clearance_maximum'))
    # Watershed boundaries suggest door passages; these always require review.
    near=ndimage.maximum_filter(grown,size=3);low=ndimage.minimum_filter(np.where(grown>1,grown,9999),size=3)
    boundary=(grown==-1)&free&(distance>.28)&(distance<.85)&(low<near)&(low>1)
    components,n=ndimage.label(boundary)
    for i in range(1,n+1):
        ys,xs=np.where(components==i)
        if len(xs)<2:continue
        pick=int(np.argmin(distance[ys,xs]));x=int(xs[pick]);y=int(ys[pick]);p=world(x,y)
        if any(math.hypot(p[0]-q['position'][0],p[1]-q['position'][1])<.9 for q in pois if q['kind']=='door'):continue
        pois.append(dict(id='door_'+str(i),name='门口候选 '+str(sum(q['kind']=='door' for q in pois)+1),kind='door',position=p,yaw=0.,confirmed=False,source='geometric_passage'))
        if sum(q['kind']=='door' for q in pois)>=30:break
    for index,p in enumerate(known):
        name=p.get('display_name','')
        kind='elevator_wait' if '电梯' in name else 'home' if '充电' in name else None
        if kind:pois.append(dict(id='import_'+str(index),name=name,kind=kind,position=[p['x'],p['y']],yaw=p.get('yaw',0.),confirmed=False,source='existing_waypoint_hint'))
    return dict(rooms=rooms,pois=pois,map_fingerprint=hashlib.sha256(image+json.dumps(info,sort_keys=True).encode()).hexdigest(),note='房间名称来自已有标记或临时编号；门口是几何候选，需确认。电梯无法仅凭地图形状可靠识别。')
