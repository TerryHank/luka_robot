"""Convert a saved observation pose into a navigation target, never a box center."""
import math

def target_from_job(job,floor,info):
    if not job.get('hits'):raise ValueError('还没有找到物品，请先查找')
    for hit in job['hits']:
        context=hit.get('observation') or {}
        if context.get('floor_id')!=floor or context.get('map_pose_status')!='tf_at_capture_time':continue
        tf=context.get('map_from_base') or {};p=tf.get('translation',[]);q=tf.get('quaternion_xyzw',[])
        if len(p)!=3 or len(q)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in p+q):continue
        if abs(sum(v*v for v in q)-1)>.05:continue
        dx=p[0]-info['origin_x'];dy=p[1]-info['origin_y'];a=-info.get('origin_yaw',0)
        x=math.cos(a)*dx-math.sin(a)*dy;y=math.sin(a)*dx+math.cos(a)*dy
        if not (0<=x<info['width']*info['resolution'] and 0<=y<info['height']*info['resolution']):continue
        yaw=math.atan2(2*(q[3]*q[2]+q[0]*q[1]),1-2*(q[1]**2+q[2]**2))
        return dict(id='object_observation',display_name=job['query']+'的观察位置',query=job['query'],
                    x=p[0],y=p[1],yaw=yaw,seconds=hit['seconds'],image=hit.get('image'),
                    session=job['session'],job_id=job['id'])
    raise ValueError('这次结果没有同楼层的有效观察位置，不能直接带你过去')
