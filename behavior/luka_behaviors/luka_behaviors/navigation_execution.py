import math,time,threading
from rclpy.action import ActionClient
from nav2_msgs.action import NavigateToPose
from nav2_msgs.msg import CollisionMonitorState
from std_msgs.msg import String
from std_srvs.srv import SetBool

def initialize(self):
    self.nx_nav=ActionClient(self,NavigateToPose,'/navigate_to_pose')
    self.nx_gate=self.create_client(SetBool,'/nx/navigation_enable')
    self.nx_handle=None
    self.nx_nav_outcome=None
    self.nx_status='导航待命'
    self.nx_lock=threading.Lock()
    self.nx_nav_match=None
    self.nx_nav_retry=0
    self.nx_nav_cancel_requested=False
    self.nx_collision_active=False
    self.nx_collision_since=0.0
    self.nx_collision_last_at=0.0
    self.nx_escape_attempted=False
    self.nx_escape_active=False
    self.create_subscription(CollisionMonitorState,'/collision_monitor_state',lambda msg:on_collision_state(self,msg),10)

def wait(future,seconds=4):
    end=time.monotonic()+seconds
    while not future.done() and time.monotonic()<end:time.sleep(.02)
    if not future.done():raise ValueError('导航服务响应超时')
    return future.result()

def gate(self,enabled):
    if not self.nx_gate.service_is_ready():raise ValueError('底盘导航开关未就绪')
    result=wait(self.nx_gate.call_async(SetBool.Request(data=enabled)))
    if not result.success:raise ValueError(result.message)

def speak_nav(self,text):
    """Send one navigation status sentence through the existing local TTS path."""
    text=str(text or '').strip()
    if text and hasattr(self,'nx_speech_pub'):
        self.nx_speech_pub.publish(String(data='speech: '+text))

def on_collision_state(self,msg):
    """Translate Collision Monitor STOP transitions into user-facing voice status."""
    # APPROACH/SLOWDOWN can also hold the commanded velocity at zero while the
    # controller waits for a safe corridor, so every non-zero safety action is
    # treated as an obstacle transition for speech purposes.
    active=int(getattr(msg,'action_type',0)) != int(CollisionMonitorState.DO_NOTHING)
    now=time.monotonic()
    if active:
        if self.nx_handle is not None:
            self.nx_collision_last_at=now
        if not self.nx_collision_active and self.nx_handle is not None:
            self.nx_collision_active=True
            self.nx_collision_since=now
            name=(self.nx_nav_match or {}).get('display_name','目标位置')
            speak_nav(self,'前方有人或障碍物，我先停车；清开后会继续前往'+name+'。')
        return
    if self.nx_collision_active:
        self.nx_collision_active=False
        if self.nx_handle is not None and self.nx_nav_match is not None and not self.nx_nav_cancel_requested:
            speak_nav(self,'前方已清开，我继续前往'+self.nx_nav_match.get('display_name','目标位置')+'。')

def stop_nav(self,wait_for_gate=True):
    """Cancel the active action and disable the navigation gate."""
    if hasattr(self,'escape_recovery'):
        self.escape_recovery.cancel('用户已停止导航')
    with self.nx_lock:
        self.nx_nav_cancel_requested=True
        self.nx_nav_retry=0
        handle=self.nx_handle
        if handle is not None:
            try: handle.cancel_goal_async()
            except Exception: pass
            self.nx_nav_outcome=5
        self.nx_status='导航已停止'
    try:
        if wait_for_gate:
            gate(self,False)
        elif self.nx_gate.service_is_ready():
            self.nx_gate.call_async(SetBool.Request(data=False))
    except Exception: pass

def send_nav(self,poi_id,observation=None):
    with self.nx_lock:
        if self.follow_controller.enabled:raise ValueError('请先停止人体跟随再导航')
        if self.relocalization.running:raise ValueError('正在重定位，请完成并核对位置后再导航')
        if self.current_floor_id!='floor_4':raise ValueError('当前导航仅开放四楼地图')
        if self.nx_handle is not None:raise ValueError('请先停止当前导航再选择新航点')
        if self.nx_escape_active:raise ValueError('脱困检查正在进行，请稍候或点击停车')
        match=observation or next((w for w in self.behaviors.navigate.catalog() if w['id']==str(poi_id)),None)
        if match is None:raise ValueError('四楼没有该航点')
        if hasattr(self,'web_teleop') and self.web_teleop.status()['session_active']:
            raise ValueError('请先松开网页摇杆，再启动导航')
        if not self.nx_nav.server_is_ready():raise ValueError('导航服务未就绪')
        localization=self.product.localization_status()
        if not localization.get('ready'):
            raise ValueError('定位未通过地图核验，暂不导航：'+str(localization.get('reason','状态未知')))
        if not self.behaviors.navigate.verified(localization):
            raise ValueError('定位候选尚未通过高置信雷达与重复定位核验；暂不导航，请等待自动重定位完成')
        if hasattr(self,'web_teleop'):self.web_teleop.force_stop()
        gate(self,True)
        self.nx_nav_match=match
        self.nx_nav_retry=0
        self.nx_nav_cancel_requested=False
        self.nx_nav_outcome=None
        self.nx_collision_last_at=0.0
        self.nx_escape_attempted=False
        def make_goal(target):
            goal=NavigateToPose.Goal();goal.pose.header.frame_id='map'
            goal.pose.header.stamp=self.get_clock().now().to_msg()
            goal.pose.pose.position.x=float(target['x']);goal.pose.pose.position.y=float(target['y'])
            yaw=float(target.get('yaw',0));goal.pose.pose.orientation.z=math.sin(yaw/2);goal.pose.pose.orientation.w=math.cos(yaw/2)
            return goal
        def submit(attempt=0):
            if self.nx_nav_cancel_requested:return
            try:
                handle=wait(self.nx_nav.send_goal_async(make_goal(match)))
                if not handle.accepted:raise ValueError('导航服务拒绝目标')
                self.nx_handle=handle;self.nx_nav_retry=attempt
                self.nx_status=('正在前往 ' if attempt==0 else '正在重新规划前往 ')+match['display_name']
                def finished(f):
                    try: result=f.result();status=int(result.status)
                    except Exception:
                        status=6
                    recent_obstacle=(time.monotonic()-self.nx_collision_last_at < 20.)
                    if (status == 6 and not self.nx_nav_cancel_requested
                            and not self.nx_escape_attempted and recent_obstacle
                            and hasattr(self,'escape_recovery') and self.escape_recovery.enabled):
                        self.nx_escape_attempted=True
                        self.nx_escape_active=True
                        self.nx_handle=None
                        self.nx_status='贴障停车，正在检查短距离脱困'
                        def recover():
                            try:
                                gate(self,False)
                                if self.nx_nav_cancel_requested:return
                                outcome=self.escape_recovery.run(
                                    lambda:self.web_teleop.status()['session_active'])
                                if self.nx_nav_cancel_requested:return
                                if outcome['ok']:
                                    self.nx_status='已脱困，正在重新规划'
                                    gate(self,True)
                                    submit(attempt+1)
                                    return
                                self.nx_status='脱困未通过安全检查：'+outcome['reason']
                            except Exception as exc:
                                self.nx_status='脱困中止：'+str(exc)
                            finally:
                                self.nx_escape_active=False
                            if not self.nx_nav_cancel_requested:
                                self.nx_nav_outcome=6
                                self.nx_collision_active=False
                                if not self.patrol_mission.active():
                                    speak_nav(self,'附近空间不足，我已停车，请帮我移开障碍。')
                        threading.Thread(target=recover,daemon=True).start()
                        return
                    if (status != 4 and not self.nx_nav_cancel_requested and
                            attempt < 2 and not self.nx_escape_attempted):
                        self.nx_nav_outcome=None
                        self.nx_nav_retry=attempt+1
                        self.nx_status='障碍或路径暂不可用，正在第 '+str(attempt+1)+' 次重试'
                        threading.Thread(target=lambda:(time.sleep(1.5),submit(attempt+1)),daemon=True).start()
                        return
                    self.nx_handle=None
                    self.nx_nav_outcome=status
                    self.nx_status={4:'已到达',5:'已取消',6:'导航失败，请检查路线或定位'}.get(status,'导航已结束')
                    self.nx_collision_active=False
                    try:self.nx_gate.call_async(SetBool.Request(data=False))
                    except Exception:pass
                    mission_active=hasattr(self,'patrol_mission') and self.patrol_mission.active()
                    name=match.get('display_name','目标位置')
                    if not mission_active:
                        if status==4:speak_nav(self,'已到达'+name+'。接下来要我做什么？')
                        elif status==6:speak_nav(self,'到不了'+name+'，我已停在当前位置。接下来要我做什么？')
                        elif status==5 and not self.nx_nav_cancel_requested:speak_nav(self,'导航已停止。接下来要我做什么？')
                handle.get_result_async().add_done_callback(finished)
            except Exception:
                if attempt < 2 and not self.nx_nav_cancel_requested:
                    self.nx_nav_retry=attempt+1
                    threading.Thread(target=lambda:(time.sleep(1.5),submit(attempt+1)),daemon=True).start()
                    return
                self.nx_handle=None
                self.nx_nav_outcome=6;self.nx_status='导航失败，请检查路线或定位';gate(self,False)
                if not (hasattr(self,'patrol_mission') and self.patrol_mission.active()):speak_nav(self,'到不了'+match.get('display_name','目标位置')+'，我已停在当前位置。接下来要我做什么？')
        try: submit(0)
        except Exception:
            gate(self,False);raise
        return dict(ok=True,id=match['id'],display_name=match['display_name'],floor_id='floor_4')
