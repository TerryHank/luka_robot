from .policy import validate

class CapabilityDispatcher:
 def __init__(self,mission_service,behavior_service,status_service,music_service,product_service):
  self.mission_service=mission_service;self.behavior_service=behavior_service
  self.status_service=status_service;self.music_service=music_service;self.product_service=product_service

 def execute(self,tool,args,source):
  validate(tool,args,source)
  mission=self.mission_service
  if tool=='destinations':return '可以前往：'+'、'.join(p['display_name'] for p in self.status_service.destinations())
  if tool=='follow_status':
   state=self.behavior_service.follow.snapshot()
   return ('人体跟随'+('已开启' if state.get('enabled') else '未开启')+
           '；'+str(state.get('reason') or state.get('ready_reason') or '状态未知'))
  if tool=='follow_start':
   state=self.behavior_service.follow.start()
   return ('已开始人体跟随。'+str(state.get('reason') or '目标或障碍不确定时会自动停车'))
  if tool=='follow_stop':
   self.behavior_service.acquisition.cancel()
   state=self.behavior_service.follow.stop('已通过助手停止跟随')
   return '已停止人体跟随并请求停车。'+str(state.get('reason') or '')
  if tool=='navigate':
   name=args.get('name',args.get('waypoint',''));hits=[p for p in self.status_service.destinations() if p['display_name']==name or p['id']==name]
   if len(hits)!=1 or hits[0]['display_name'] not in source:raise ValueError('请明确说出一个已确认的航点名称')
   if mission.active():raise ValueError('请先停止当前巡航或找物任务')
   self.behavior_service.navigate(hits[0]['id']);return '已提交前往'+hits[0]['display_name']+'的导航。'
  if tool=='cancel_all':
   if hasattr(self.behavior_service,'cancel_all'):
    result=self.behavior_service.cancel_all()
    if not result['ok']:raise ValueError('停止未完全确认：'+'；'.join(result['errors']))
    return result['results']['patrol']['message']
   self.behavior_service.acquisition.cancel()
   self.behavior_service.follow.stop('已通过助手停止全部运动')
   return mission.stop()['message']
  if tool=='patrol_stop':return mission.stop()['message']
  if tool=='patrol_start':return mission.start()['message']
  if tool=='patrol_route':
   r=mission.route_snapshot()
   if r['error']:raise ValueError(r['error'])
   return '当前巡航路线：'+'、'.join(p['display_name'] for p in r['points'])+'，巡航一遍。'
  if tool=='patrol_route_set':
   names=args.get('names');rows=self.status_service.destinations()
   if not isinstance(names,list) or not 1<=len(names)<=30:raise ValueError('请提供巡航航点顺序')
   ids=[];at=0
   for name in names:
    if not isinstance(name,str):raise ValueError('航点名称无效')
    found=source.find(name,at);hits=[p for p in rows if p['display_name']==name]
    if found<0 or len(hits)!=1:raise ValueError('航点顺序必须与你的原话一致')
    at=found+len(name);ids.append(hits[0]['id'])
   r=mission.route_snapshot();mission.save_route({'revision':r['revision'],'ids':ids,'dwell_s':args.get('dwell_s',r['dwell_s']) if '秒' in source else r['dwell_s']})
   return '路线已保存：'+'、'.join(names)+'。尚未启动巡航。'
  if tool=='find_object':return mission.search(args.get('query'))['message']
  if tool=='object_bring' and args.get('query') in {p['display_name'] for p in self.status_service.destinations()}:raise ValueError('这是目的地而非寻物目标，请明确要导航还是找物')
  if tool in ('object_where','object_bring'):
   if tool=='object_where':return mission.answer(args.get('query'))
   return mission.bring({'query':args.get('query')})['message']
  if tool=='localization_status':return self.product_service.localization_status()['reason']
  if tool=='localization_auto':
   if mission.active() or self.status_service.navigation_active:raise ValueError('请先停车结束任务')
   
   with self.status_service.navigation_lock:self.behavior_service.relocalize.start('auto',{})
   return '已开始尝试重定位，完成后请在地图上核对位置。'
  if tool=='functions_status':
   return '；'.join(s['name']+('运行中' if s['state']=='active' else '未运行') for s in self.status_service.functions.status()['services'])
  if tool=='functions_start':
   if mission.active() or self.status_service.navigation_active:raise ValueError('请先结束当前任务并停车')
   return self.status_service.functions.start()['message']
  if tool=='voice_volume':
   self.status_service.set_voice_volume(args['direction'])
   return '已请求调'+('大' if args['direction']=='up' else '小')+'说话音量。'
  if tool in ('record_start','record_stop','record_status','camera_find'):
   if tool=='record_status':
    s=self.status_service.vision('/patrol/status');return '正在录像。' if s.get('recording') else '目前没有正在录制的视频。'
   if mission.active() or self.status_service.navigation_active:raise ValueError('请先结束当前任务并停车')
   if tool=='record_start':self.status_service.vision('/patrol/start',{});return '已请求开始原地录像。'
   if tool=='record_stop':self.status_service.vision('/patrol/stop',{});return '已请求停止并保存录像。'
   self.status_service.vision('/locate',{'query':args.get('query')});return '已提交相机识别，请在画面查看结果。'
  if tool=='robot_status':return '当前任务：'+mission.snapshot()['message']+'。定位：'+self.product_service.localization_status()['reason']+'。超声波已关闭。'
  if tool=='voiceprint_status':
   s=self.status_service.voiceprint_status();r=s.get('result') or {}
   return '已录入'+str(sum(p['ready'] for p in s['profiles']))+'个声纹。最近记录为'+str(r.get('name') or '未确定说话人')+'，不是身份认证。'
  if tool.startswith('music_'):return self.music_service.action(tool.removeprefix('music_'),args)
  if tool=='settings_help':return '我可以导航、按路线巡航并实时记住物品、查询物体记忆并带路、查询定位和声纹、管理音乐，也可以按你的要求单独录像。账号联网、地图房间航点编辑、声纹录入和手动定位请在客户页操作；启动重启在监控页。电梯和自主建图尚未接通，超声波已关闭。'
