#!/usr/bin/env python3
"""Fixed Foxglove experiment services and visualization; never publish motor commands."""
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import threading
import time

import cv2
from cv_bridge import CvBridge
import rclpy
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rcl_interfaces.srv import GetParameters
from sensor_msgs.msg import Image, CompressedImage
from ai_msgs.msg import PerceptionTargets
from nav2_msgs.action import NavigateToPose, Spin
from std_msgs.msg import String
from std_srvs.srv import Trigger, SetBool
from tf2_ros import Buffer, TransformListener

WS=Path('/home/sunrise/luka_ws')
PREFIX='/person_follow/gui'


def service_result(response):
    if response is None or not response.success:
        raise RuntimeError('服务拒绝请求' if response is None else response.message)
    return response


class GuiManager(Node):
    def __init__(self):
        super().__init__('person_follow_gui')
        self.group=ReentrantCallbackGroup()
        self.lock=threading.Lock()
        self.epoch=0
        self.process=None
        self.process_log=None
        self.mode='unknown'
        self.mode_at=0.
        self.live_verified=False
        self.last_error=''
        self.follow_status='DISABLED'
        self.diagnostic='等待预览链启动'
        self.mot=None
        self.mot_at=self.image_at=self.preview_at=0.
        self.bridger=CvBridge()
        self.tf=Buffer();self.listener=TransformListener(self.tf,self)
        self.nav=ActionClient(self,NavigateToPose,'/navigate_to_pose',callback_group=self.group)
        self.spin=ActionClient(self,Spin,'/spin',callback_group=self.group)
        self.parameters=self.create_client(GetParameters,'/person_follow/tros_person_following_node/get_parameters',callback_group=self.group)
        self.follow=self.create_client(SetBool,'/person_follow/enable_follow',callback_group=self.group)
        self.base_follow=self.create_client(SetBool,'/nx/follow_enable',callback_group=self.group)
        self.base_nav=self.create_client(SetBool,'/nx/navigation_enable',callback_group=self.group)
        self.state_pub=self.create_publisher(String,PREFIX+'/state',10)
        self.preview_pub=self.create_publisher(CompressedImage,PREFIX+'/image/compressed',2)
        self.create_subscription(Image,'/camera/color/image_raw',self.image,qos_profile_sensor_data)
        self.create_subscription(PerceptionTargets,'/tros_mot_targets',self.targets,qos_profile_sensor_data)
        self.create_subscription(String,'/person_follow/tros_tracking_status',self.status,10)
        self.create_subscription(String,'/person_follow/integration_diagnostics',self.diagnose,10)
        self.create_timer(1.,self.publish_state,callback_group=self.group)
        for name,operation in [('start_preview',self.start_preview),('enable_observation',self.enable_observation),
                               ('prepare_base',self.prepare_base),('stop',self.stop),('close_preview',self.close_preview)]:
            callback=self.stop_handler if name=='stop' else self.handler(operation)
            self.create_service(Trigger,PREFIX+'/'+name,callback,callback_group=self.group)
        self.create_service(SetBool,PREFIX+'/prepare_action_mode',self.prepare_action_mode,callback_group=self.group)

    def handler(self,operation):
        def handle(_request,response):
            if not self.lock.acquire(False):
                response.success=False;response.message='上一个操作尚未结束';return response
            try:
                generation=self.epoch
                response.message=operation();response.success=True;self.last_error=''
                if generation!=self.epoch and operation!=self.close_preview:
                    self.stop();response.success=False;response.message='操作期间收到停止，保持关闭'
            except Exception as error:
                self.last_error=str(error);response.success=False;response.message=self.last_error
            finally:self.lock.release()
            return response
        return handle

    def stop_handler(self,_request,response):
        try:response.message=self.stop();response.success=True
        except Exception as error:response.message=str(error);response.success=False
        return response

    def call(self,client,request,timeout=3.):
        if not client.wait_for_service(timeout_sec=.3):raise RuntimeError('服务未就绪：'+client.srv_name)
        future=client.call_async(request);deadline=time.monotonic()+timeout
        while not future.done() and time.monotonic()<deadline:time.sleep(.02)
        if not future.done():raise RuntimeError('服务响应超时：'+client.srv_name)
        return future.result()

    def read_mode(self):
        if not self.parameters.service_is_ready():
            self.mode='unknown';return self.mode
        response=self.call(self.parameters,GetParameters.Request(names=['output_mode']),timeout=1.)
        self.mode=response.values[0].string_value if response and response.values else 'unknown'
        self.mode_at=time.monotonic();return self.mode

    def production_ready(self):
        return (self.nav.server_is_ready() and self.spin.server_is_ready() and
                self.count_publishers('/global_costmap/costmap')>0 and
                self.count_publishers('/wheel/odom')>0 and
                self.tf.can_transform('map','base_link',rclpy.time.Time()) and
                self.tf.can_transform('map','camera_link',rclpy.time.Time()))

    def close_base(self):
        errors=[]
        for client in (self.base_follow,self.base_nav):
            if client.service_is_ready():
                try:service_result(self.call(client,SetBool.Request(data=False)))
                except Exception as error:errors.append(str(error))
        if errors:raise RuntimeError('; '.join(errors))

    def start(self,mode):
        if self.follow.service_is_ready():
            existing=self.read_mode()
            if existing==mode:return '复用现有 '+mode+' 跟随入口，未启动重复节点'
            raise RuntimeError('已有其他模式的跟随节点；先停止并关闭它')
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError('预览仍在启动，请等待状态')
        (WS/'log/person_follow_gui').mkdir(parents=True,exist_ok=True)
        if self.process_log:self.process_log.close()
        self.process_log=(WS/'log/person_follow_gui/launch.log').open('w')
        command=['/bin/bash',str(WS/'src/system/scripts/start_official_person_following.sh'),
                 'output_mode:='+mode,'follow_enabled_on_start:=false']
        if mode=='nav2_action':command.append('input_contract_verified:=true')
        for topic,flag in [('/hobot_dnn_seg','start_segmentation'),('/tros_fusion_interaction','start_depth_fusion'),('/tros_mot_targets','start_mot')]:
            if self.count_publishers(topic)>0:command.append(flag+':=false')
        self.process=subprocess.Popen(command,stdout=self.process_log,stderr=subprocess.STDOUT,start_new_session=True)
        self.mode='unknown';self.follow_status='DISABLED';self.diagnostic='等待新入口';self.mot=None
        return '已提交 '+mode+' 启动，等待节点和图像；算法保持关闭'

    def start_preview(self):
        if self.count_publishers('/camera/color/image_raw')==0:
            subprocess.run(['sudo','-n','systemctl','start','luka-ws-orbbec-camera.service'],check=True,timeout=15)
        return self.start('dry_run')

    def enable_observation(self):
        if self.read_mode()!='dry_run':raise RuntimeError('观察按钮只允许已确认的 dry_run 模式')
        service_result(self.call(self.follow,SetBool.Request(data=True)))
        return 'dry-run 策略已启用，不下发真实导航或旋转'

    def prepare_base(self):
        if not (WS/'src/common/config/nx_manual_mode').exists():raise RuntimeError('缺少当前底盘所有者标记，先核查串口归属')
        if self.count_publishers('/wheel/odom')>0 and not self.base_follow.service_is_ready():
            raise RuntimeError('已有其他里程计/底盘所有者，未另起串口驱动')
        for name in ('sensors','manual_base'):
            subprocess.run(['sudo','-n','systemctl','start','luka-ws-hardware@'+name+'.service'],check=True,timeout=15)
        if not self.base_follow.wait_for_service(timeout_sec=5):raise RuntimeError('底盘服务未就绪，未启动后续导航')
        self.close_base()
        for name in ('localization','navigation'):
            subprocess.run(['sudo','-n','systemctl','start','luka-ws-hardware@'+name+'.service'],check=True,timeout=15)
        return '基础栈已请求启动，底盘许可关闭；请检查当前场地地图与初始定位'

    def stop(self):
        self.epoch+=1;self.live_verified=False
        errors=[]
        if self.follow.service_is_ready():
            try:service_result(self.call(self.follow,SetBool.Request(data=False)))
            except Exception as error:errors.append(str(error))
        try:self.close_base()
        except Exception as error:errors.append(str(error))
        if errors:raise RuntimeError('; '.join(errors))
        return '已请求取消跟随并关闭底盘许可；以实测里程计确认停稳'

    def close_preview(self):
        self.stop()
        if self.process is not None and self.process.poll() is None:
            os.killpg(self.process.pid,signal.SIGINT)
            try:self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:raise RuntimeError('预览未完成关闭，请检查 launch.log，未强杀')
        self.process=None;self.mode='unknown'
        return '本界面启动的预览链已关闭；外部启动的节点未关闭'

    def prepare_action_mode(self,request,response):
        if not self.lock.acquire(False):response.success=False;response.message='上一个操作尚未结束';return response
        try:
            if not request.data:raise RuntimeError('须由操作者确认当前地图、定位和感知输入已验收')
            if not self.production_ready():raise RuntimeError('生产定位、地图、里程计或 Nav2 动作接口未就绪')
            if self.process is None and self.follow.service_is_ready():raise RuntimeError('外部跟随入口正在运行，未替换它')
            self.close_preview();generation=self.epoch;self.live_verified=True
            response.message=self.start('nav2_action');response.success=True
            if generation!=self.epoch:self.stop();response.success=False;response.message='期间收到停止，动作模式未放行'
        except Exception as error:response.success=False;response.message=str(error);self.last_error=str(error)
        finally:self.lock.release()
        return response

    def status(self,message):self.follow_status=message.data
    def diagnose(self,message):self.diagnostic=message.data
    def targets(self,message):self.mot=message;self.mot_at=time.monotonic()

    def image(self,message):
        self.image_at=time.monotonic()
        if self.preview_pub.get_subscription_count()==0 or self.image_at-self.preview_at<.25:return
        self.preview_at=self.image_at
        try:
            frame=self.bridger.imgmsg_to_cv2(message,'bgr8').copy()
            mot=self.mot
            if mot is not None and self.image_at-self.mot_at<.6:
                delta=(mot.header.stamp.sec-message.header.stamp.sec)+(mot.header.stamp.nanosec-message.header.stamp.nanosec)*1e-9
                if abs(delta)<.2 and mot.header.frame_id==message.header.frame_id:
                    for target in mot.targets:
                        if target.type!='person':continue
                        roi=next((r for r in target.rois if r.type=='person'),None)
                        if roi is None:continue
                        rect=roi.rect;x,y=int(rect.x_offset),int(rect.y_offset)
                        x2,y2=min(frame.shape[1]-1,x+int(rect.width)),min(frame.shape[0]-1,y+int(rect.height))
                        if x<0 or y<0 or x2<=x or y2<=y:continue
                        depth=next((a.value/100 for a in target.attributes if a.type=='x_cm'),None)
                        label='ID '+str(target.track_id)+((' %.2fm'%depth) if depth is not None and math.isfinite(depth) else '')
                        cv2.rectangle(frame,(x,y),(x2,y2),(0,220,80),2)
                        cv2.putText(frame,label,(x,max(18,y-5)),cv2.FONT_HERSHEY_SIMPLEX,.55,(0,220,80),2)
            cv2.putText(frame,self.mode+' | '+self.follow_status.split(':')[0][-30:],(8,22),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,220,0),1)
            ok,data=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,75])
            if ok:
                output=CompressedImage();output.header=message.header;output.format='jpeg';output.data=data.tobytes();self.preview_pub.publish(output)
        except Exception as error:self.last_error='预览图像：'+type(error).__name__

    def publish_state(self):
        try:self.read_mode()
        except Exception:self.mode='unknown'
        now=time.monotonic();targets=[]
        if self.mot is not None and now-self.mot_at<.6:
            targets=[{'track_id':t.track_id,'confidence':next((r.confidence for r in t.rois if r.type=='person'),0.)} for t in self.mot.targets if t.type=='person']
        launch_code=self.process.poll() if self.process is not None else None
        if launch_code is not None:self.last_error='预览退出 '+str(launch_code)+'；查看 log/person_follow_gui/launch.log'
        body={'output_mode':self.mode,'follow_status':self.follow_status,'diagnostic':self.diagnostic,
              'production_ready':bool(self.production_ready()),'live_verified':self.live_verified,
              'camera_fresh':now-self.image_at<1.,'mot_fresh':now-self.mot_at<.6,'targets':targets,
              'owned_preview':self.process is not None and launch_code is None,'error':self.last_error}
        self.state_pub.publish(String(data=json.dumps(body,ensure_ascii=False)))

    def shutdown(self):
        if self.process is not None and self.process.poll() is None:
            os.killpg(self.process.pid,signal.SIGINT)
            try:self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:self.get_logger().error('Preview shutdown still pending')
        if self.process_log:self.process_log.close()


def main():
    rclpy.init();node=GuiManager();executor=MultiThreadedExecutor(num_threads=4);executor.add_node(node)
    try:executor.spin()
    except KeyboardInterrupt:pass
    finally:node.shutdown();executor.shutdown();node.destroy_node();rclpy.try_shutdown()


if __name__=='__main__':main()
