import math,time

def current_scope(node):
    # Import lazily so non-ROS mission tests can exercise motion interlocks.
    from object_pose_context import map_scope
    scope=map_scope(node)
    if not scope.get('map_scope_valid') or not scope.get('map_id'):
        raise ValueError('当前地图范围未确认：'+str(scope.get('map_scope_reason') or '等待地图'))
    return scope

def describe_entities(query,objects):
    if not objects:return '当前地图的物体记忆中暂未找到'+query+'。尚未记录不代表物品不在。'
    descriptions=[]
    for entity in objects[:3]:
        description=entity.get('description') or entity.get('name_zh') or entity.get('label') or query
        stamp=entity.get('last_seen')
        when=time.strftime('%m月%d日%H点%M分',time.localtime(stamp)) if isinstance(stamp,(int,float)) and math.isfinite(stamp) and stamp>0 else '之前'
        place=('观察点'+entity['area_hint']) if entity.get('area_hint') else '已记录的观察位置'
        descriptions.append('在'+when+'于'+place+'看到过'+description)
    text=('记忆中有'+str(len(objects))+'个匹配物品。' if len(objects)>1 else '找到一条物体记忆。')+'；'.join(descriptions)+'。这是上次看到的位置，物品可能已经移动。'
    if len(objects)>1:text+='请在页面选择其中一个，再说带我去。'
    elif objects[0].get('observation_pose') and not objects[0].get('identity_uncertain'):text+='你可以说带我去，到观察位置后重新确认。'
    else:text+='目前缺少可用于带路的可靠观察位置。'
    return text
