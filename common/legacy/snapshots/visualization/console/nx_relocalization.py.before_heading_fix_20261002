"""AMCL controls with bounded, guarded rotation for global relocalization."""
import math,time,threading
from geometry_msgs.msg import PoseWithCovarianceStamped
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from std_srvs.srv import Empty, SetBool
from rclpy.qos import qos_profile_sensor_data
from object_pose_context import normalize_planar_covariance
from nx_scan_map_match import ScanMapMatcher

def validate_pose(body, info):
    values=[float(body[k]) for k in ('x','y','yaw')]
    if not all(math.isfinite(v) for v in values):raise ValueError('位置与朝向必须是有限数字')
    x,y,yaw=values
    dx=x-info['origin_x'];dy=y-info['origin_y'];a=-info.get('origin_yaw',0)
    lx=math.cos(a)*dx-math.sin(a)*dy;ly=math.sin(a)*dx+math.cos(a)*dy
    if not (0<=lx<info['width']*info['resolution'] and 0<=ly<info['height']*info['resolution']):
        raise ValueError('粗定位位置必须在地图范围内')
    return x,y,math.atan2(math.sin(yaw),math.cos(yaw))

class Relocalization:
    def __init__(self,node,stop):
        self.node=node;self.stop=stop;self.lock=threading.Lock()
        self.running=False;self.message='未发起定位操作';self.pose_at=0.;self.cov=None
        self.covariance_info={'covariance_status':'unavailable','covariance_raw':None,
                             'covariance_diagonal':None,'covariance_near_zero':False}
        self.odom_at=0.;self.still_since=0.
        self.odom_yaw=None;self.rotation_progress=0.;self.last_rotation_yaw=None
        self.pose_xy=None;self.confident_since=0.;self.confident_anchor=None
        self.cancel=threading.Event()
        self.scan_matcher=ScanMapMatcher(node)
        self.pub=node.create_publisher(PoseWithCovarianceStamped,'/initialpose',10)
        self.global_client=node.create_client(Empty,'/reinitialize_global_localization')
        self.update_client=node.create_client(Empty,'/request_nomotion_update')
        # Feed the existing dual-lidar collision monitor, never its output.
        self.cmd_pub=node.create_publisher(Twist,'/nx/nav_guarded',10)
        node.create_subscription(PoseWithCovarianceStamped,'/amcl_pose',self.on_pose,10)
        node.create_subscription(Odometry,'/wheel/odom',self.on_odom,qos_profile_sensor_data)
    def on_pose(self,msg):
        now=time.monotonic();self.pose_at=now
        info=normalize_planar_covariance(getattr(msg.pose,'covariance',None))
        self.cov=info.pop('sigma')
        self.covariance_info=info
        x=float(msg.pose.pose.position.x);y=float(msg.pose.pose.position.y)
        self.pose_xy=(x,y)
        q=msg.pose.pose.orientation
        self.pose_yaw=math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
        good=(info['covariance_status']=='valid' and not info['covariance_near_zero']
              and self.cov is not None and self.cov[0]<.18 and self.cov[1]<.18 and self.cov[2]<.22)
        if not good or (self.confident_anchor and math.hypot(x-self.confident_anchor[0],y-self.confident_anchor[1])>.12):
            self.confident_since=0.;self.confident_anchor=None
        if good and not self.confident_since:
            self.confident_since=now;self.confident_anchor=(x,y)
    def on_odom(self,msg):
        now=time.monotonic();v=msg.twist.twist
        q=msg.pose.pose.orientation
        yaw=math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
        if self.last_rotation_yaw is not None:
            self.rotation_progress+=abs(math.atan2(math.sin(yaw-self.last_rotation_yaw),math.cos(yaw-self.last_rotation_yaw)))
            self.last_rotation_yaw=yaw
        self.odom_yaw=yaw
        still=math.hypot(v.linear.x,v.linear.y)<.025 and abs(v.angular.z)<.04
        self.still_since=(self.still_since or now) if still else 0.
        self.odom_at=now
    def snapshot(self):
        alignment=self.alignment()
        assessment=''
        if not self.running and alignment.get('valid'):
            if self.covariance_info.get('covariance_near_zero'):
                assessment='静态雷达与地图匹配，但 AMCL 协方差接近零；定位可靠性尚未通过位移验证，禁止行驶'
            elif not self.pose_at:
                assessment='静态雷达与地图匹配；等待 AMCL 位姿及协方差更新，禁止行驶'
            else:
                assessment='已有静态位置估计且雷达与地图匹配；请核对实际位置，行驶尚未验收'
        if (not self.running and self.pose_at and self.covariance_info.get('covariance_status') in ('valid','roundoff_clamped')
                and not alignment.get('valid')):
            median=alignment.get('median_m')
            assessment='AMCL 位姿已收到，但雷达与地图尚未匹配'
            if median is not None:assessment+='（端点中位误差 %.2f 米，15厘米内 %.0f%%）'%(median,100*(alignment.get('within_15cm') or 0.))
            else:assessment+='（'+str(alignment.get('reason','等待数据'))+'）'
        message=self.message if self.running or self.message!='未发起定位操作' else (assessment or self.message)
        return dict(running=self.running,message=message,
            pose_age=round(time.monotonic()-self.pose_at,2) if self.pose_at else -1,
            rotation_progress_rad=round(self.rotation_progress,2),
            uncertainty=self.cov,scan_map=alignment,assessment=assessment,**self.covariance_info)
    def alignment(self):
        # Compare the newest scan with the newest map->base transform. AMCL may
        # not publish /amcl_pose on every stationary scan, while its map->odom
        # transform and wheel odometry continue to define the current base pose.
        try:
            from rclpy.time import Time
            tf=self.node.object_pose_context.buffer.lookup_transform('map','base_link',Time())
            stamp=tf.header.stamp.sec+tf.header.stamp.nanosec/1e9
            age=time.time()-stamp
            if not -.5<=age<1.5:return self.scan_matcher.empty('map_to_base_tf_stale')
            t,q=tf.transform.translation,tf.transform.rotation
            yaw=math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
            return self.scan_matcher.score((t.x,t.y,yaw))
        except Exception as exc:
            return self.scan_matcher.empty('map_to_base_tf_unavailable:'+str(exc)[:100])
    def stop_rotation(self):
        self.cancel.set()
        self.cmd_pub.publish(Twist())
    def localized(self):
        now=time.monotonic()
        alignment=self.alignment()
        # A corner or a repeating room can yield a low AMCL covariance at the
        # wrong place. Require enough mapped returns and one clear heading.
        scan_confident=(alignment.get('valid') and
                        alignment.get('known_endpoints',0)>=80 and
                        (alignment.get('median_m') or 1.)<=.15 and
                        (alignment.get('within_15cm') or 0.)>=.65 and
                        alignment.get('heading_candidate_count')==1)
        return bool(self.confident_since and now-self.confident_since>=1.5 and
                    now-self.pose_at<1.2 and self.confident_anchor and self.pose_xy and
                    math.hypot(self.pose_xy[0]-self.confident_anchor[0],self.pose_xy[1]-self.confident_anchor[1])<.12 and
                    scan_confident)
    def call(self,client):
        if not client.service_is_ready():raise ValueError('AMCL 定位服务尚未就绪')
        f=client.call_async(Empty.Request());end=time.monotonic()+4
        while not f.done() and time.monotonic()<end:time.sleep(.03)
        if not f.done():raise ValueError('AMCL 服务响应超时')
        f.result()
    def start(self,mode,body):
        with self.lock:
            if self.running:raise ValueError('正在定位，请等待本次完成')
            if self.node.current_floor_id!='floor_4' or self.node.selected_map!='floor_4':
                raise ValueError('请先选择当前四楼地图')
            pose=validate_pose(body,self.node.map_info) if mode=='manual' else None
            now=time.monotonic()
            if now-self.odom_at>1 or not self.still_since or now-self.still_since<.7:
                raise ValueError('请松开手柄并停稳小车后再定位')
            if not self.node.last['scan'] or now-self.node.last['scan']>1:
                raise ValueError('雷达数据过期，请先恢复雷达')
            if mode=='manual' and self.pub.get_subscription_count()==0:raise ValueError('AMCL 未订阅初始位置')
            if mode=='auto' and not self.global_client.service_is_ready():raise ValueError('AMCL 全局重定位服务未就绪')
            # Stop an active goal before localization.  The HTTP handler must not
            # hold nx_lock while entering here; otherwise stop_nav deadlocks.
            self.stop()
            self.cancel.clear()
            self.running=True;self.message='正在提交粗定位' if pose else '正在检查现有定位，必要时缓慢自转扫描'
            threading.Thread(target=self.work,args=(pose,),daemon=True).start()
            return dict(ok=True,**self.snapshot())
    def work(self,pose):
        started=time.monotonic()
        try:
            if pose:
                refined,quality=self.scan_matcher.refine_near(pose)
                if quality.get('valid'):
                    self.node.get_logger().info(
                        'Saved-pose scan refinement: %.3f %.3f %.3f, median=%.3f, within15=%.3f' %
                        (*refined,quality['median_m'],quality['within_15cm']))
                    pose=refined
                msg=PoseWithCovarianceStamped();msg.header.frame_id='map';msg.header.stamp=self.node.get_clock().now().to_msg()
                x,y,yaw=pose;msg.pose.pose.position.x=x;msg.pose.pose.position.y=y
                msg.pose.pose.orientation.z=math.sin(yaw/2);msg.pose.pose.orientation.w=math.cos(yaw/2)
                msg.pose.covariance[0]=.25;msg.pose.covariance[7]=.25;msg.pose.covariance[35]=math.radians(25)**2
                self.pub.publish(msg)
            else:
                # Refresh AMCL first. A confident existing pose needs no global
                # reset and no rotation.
                for _ in range(6):
                    if self.update_client.service_is_ready():self.call(self.update_client)
                    time.sleep(.35)
                    if self.localized():
                        self.message='当前定位已稳定，无需自转；请核对地图雷达与墙体。'
                        return
                self.confident_since=0.;self.confident_anchor=None
                self.call(self.global_client)
                self.message='全地图搜索中；定位稳定后将自动停转'
                for _ in range(5):
                    if self.update_client.service_is_ready():self.call(self.update_client)
                    time.sleep(.35)
                    if self.localized():
                        self.message='静止扫描已完成定位，无需自转；请核对地图雷达与墙体。'
                        return
                self.rotate_scan()
            for _ in range(8):
                time.sleep(.7)
                if self.update_client.service_is_ready():self.call(self.update_client)
            self.message=('定位已稳定；请检查地图雷达与墙体是否重合，再导航。' if self.localized()
                          else '已收到定位估计，但稳定性仍需核对；请检查地图雷达与墙体。' if self.pose_at>started
                          else '尚未收到新的定位估计，请尝试手动粗定位并检查雷达。')
            if self.pose_at>started and self.cov is None:
                self.message='已收到定位数据，但协方差无效；请检查定位状态并重新定位。'
            if not pose and not self.localized():self.message+=' 全局重定位可能有多个候选。'
        except Exception as exc:self.message='定位未完成：'+str(exc)
        finally:self.running=False

    def rotate_scan(self):
        """Slowly rotate in place while AMCL receives a full 360-degree scan."""
        enabled=False
        try:
            # Navigation gating prevents the command from reaching the motors
            # until encoder, TF and lidar data are all fresh.
            for _ in range(12):
                try:
                    if self.node.nx_gate.service_is_ready():
                        result=self.node.nx_gate.call_async(SetBool.Request(data=True))
                        end=time.monotonic()+2
                        while not result.done() and time.monotonic()<end:time.sleep(.03)
                        if result.done() and result.result().success:
                            enabled=True;break
                except Exception:pass
                time.sleep(.5)
            if not enabled:raise ValueError('底盘自转许可未就绪，无法执行自转重定位')
            cmd=Twist();cmd.angular.z=.22
            self.rotation_progress=0.;self.last_rotation_yaw=self.odom_yaw
            started=time.monotonic()
            while time.monotonic()-started<55 and self.rotation_progress<2*math.pi-.25 and not self.cancel.is_set() and not self.localized():
                if time.monotonic()-self.odom_at>1 or time.monotonic()-self.node.last['scan']>1:
                    raise ValueError('定位期间雷达或里程计数据过期，已停止自转')
                if self.node.patrol_mission.active() or self.node.nx_handle is not None:
                    raise ValueError('其他行驶任务已接管，停止自转')
                self.cmd_pub.publish(cmd)
                time.sleep(.1)
            if self.cancel.is_set():raise ValueError('自转已由停车按钮取消')
            if not self.localized() and self.rotation_progress<2*math.pi-.25:
                raise ValueError('限定时间内未完成一圈自转，已停止；请检查底盘与避障状态')
        finally:
            self.last_rotation_yaw=None
            self.cmd_pub.publish(Twist())
            if enabled:
                try:self.node.nx_gate.call_async(SetBool.Request(data=False))
                except Exception:pass
