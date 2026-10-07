#!/usr/bin/env python3
"""Explicitly enabled, conservative single-person visual following."""
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data, QoSProfile, DurabilityPolicy
from sensor_msgs.msg import CompressedImage, LaserScan, Imu
from geometry_msgs.msg import Twist
from std_msgs.msg import Bool, String
from std_srvs.srv import Empty


def safe_command(box, previous, scans, now):
    # Full-circle clearance is deliberately conservative for this first version.
    if len(scans) != 2 or any(now-t > 0.6 or distance < 0.65 for t, distance in scans.values()):
        return None, 'obstacle_or_scan_stale'
    if box is None:
        return None, 'target_missing_or_ambiguous'
    x, y, w, h = box  # normalized coordinates
    if previous is not None and (abs(x+w/2-previous[0]-previous[2]/2) > 0.18 or
                                abs(h-previous[3]) > 0.18):
        return None, 'target_changed'
    error=x+w/2-0.5
    angular=max(-0.25,min(0.25,-error*0.6)) if abs(error)>0.06 else 0.0
    forward=min(0.12,max(0.0,(0.55-h)*0.45)) if abs(error)<0.18 else 0.0
    return (forward,angular), 'tracking'


class PersonFollow(Node):
    def __init__(self):
        super().__init__('person_follow')
        cv2.setNumThreads(1)
        self.hog=cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self.pool=ThreadPoolExecutor(max_workers=1)
        self.future=None
        self.frame=None
        self.last_image_stamp=None
        self.last_imu=None
        self.scans={}
        self.mode='disabled'
        self.previous=None
        self.target=None
        self.target_time=0.0
        self.stable=0
        self.epoch=0
        self.manual=False
        self.last_infer=0.0
        self.last_report=0.0
        self.reason='disabled'
        self.cmd=self.create_publisher(Twist,'/cmd_vel_nav',10)
        qos=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.active=self.create_publisher(Bool,'/person_follow/active',qos)
        self.status=self.create_publisher(String,'/person_follow/status',10)
        self.pause=self.create_client(Empty,'/hotel/mission/pause_now')
        self.resume=self.create_client(Empty,'/base_control/resume_now')
        self.create_subscription(CompressedImage,'/camera/color/image_raw/compressed',self.image,qos_profile_sensor_data)
        self.create_subscription(Imu,'/imu/data',self.imu,qos_profile_sensor_data)
        for topic in ('/scan','/scan_low_filtered'):
            self.create_subscription(LaserScan,topic,lambda msg,t=topic:self.scan(t,msg),qos_profile_sensor_data)
        self.create_subscription(Bool,'/gamepad/enabled',self.gamepad,10)
        self.create_subscription(String,'/hotel/mission/status',self.mission,10)
        self.create_service(Empty,'/person_follow/start',self.start)
        self.create_service(Empty,'/person_follow/stop',self.stop_service)
        self.create_timer(0.05,self.tick)
        self.active.publish(Bool(data=False))

    def image(self,msg):
        # Retain only latest image, not an unbounded inference queue.
        age=(self.get_clock().now().nanoseconds/1e9-msg.header.stamp.sec-msg.header.stamp.nanosec/1e9)
        if -0.2 <= age <= 0.6:
            stamp=(msg.header.stamp.sec,msg.header.stamp.nanosec)
            if stamp == self.last_image_stamp or not msg.data:
                return
            self.last_image_stamp=stamp
            self.frame=(time.monotonic()-max(0.0,age),bytes(msg.data))

    def imu(self,msg):
        age=self.get_clock().now().nanoseconds/1e9-msg.header.stamp.sec-msg.header.stamp.nanosec/1e9
        if -0.2 <= age <= 0.6 and msg.angular_velocity_covariance[0] != -1 and all(
                math.isfinite(x) for x in (msg.angular_velocity.x,msg.angular_velocity.y,msg.angular_velocity.z)):
            self.last_imu=time.monotonic()-max(0.0,age)

    def input_fault(self,now):
        if self.last_imu is None or now-self.last_imu>0.6:
            return 'imu_stale'
        if self.frame is None or now-self.frame[0]>0.6:
            return 'camera_stale'
        _, reason=safe_command((0.4,0.2,0.2,0.5),None,self.scans,now)
        return None if reason=='tracking' else reason

    def scan(self,topic,msg):
        age=self.get_clock().now().nanoseconds/1e9-msg.header.stamp.sec-msg.header.stamp.nanosec/1e9
        if not -0.2 <= age <= 0.6:
            return
        values=[x for x in msg.ranges if math.isfinite(x) and msg.range_min<=x<=msg.range_max]
        self.scans[topic]=(time.monotonic()-max(0.0,age),min(values) if values else 0.0)

    def gamepad(self,msg):
        self.manual=msg.data
        if self.manual:
            self.stop('manual_takeover')

    def mission(self,msg):
        if self.mode not in ('disabled','pausing') and msg.data in ('running','resuming','canceling','canceled'):
            self.stop('mission_changed')

    def start(self,request,response):
        if self.mode!='disabled':
            return response
        now=time.monotonic()
        fault=self.input_fault(now)
        if self.manual or fault:
            self.reason='manual_takeover' if self.manual else fault
            return response
        if not self.pause.service_is_ready() or not self.resume.service_is_ready():
            self.reason='start_rejected_services_not_ready'
            return response
        self.mode='pausing'
        self.epoch+=1
        epoch=self.epoch
        self.active.publish(Bool(data=True))
        self.transition_time=now
        future=self.pause.call_async(Empty.Request())
        future.add_done_callback(lambda f:self.paused(f,epoch))
        return response

    def paused(self,future,epoch):
        if epoch!=self.epoch or self.mode!='pausing':
            return
        try:
            future.result()
        except Exception:
            self.stop('pause_failed');return
        fault=self.input_fault(time.monotonic())
        if fault:
            self.stop(fault);return
        # Pause service cancels auto tasks and sends a zero burst before reply.
        self.mode='arming'
        self.resume.call_async(Empty.Request()).add_done_callback(lambda f:self.armed(f,epoch))

    def armed(self,future,epoch):
        if epoch!=self.epoch or self.mode!='arming':
            return
        try:
            future.result()
        except Exception:
            self.stop('base_resume_failed');return
        self.mode='seeking'
        self.previous=None
        self.target=None
        self.stable=0
        self.seek_since=time.monotonic()

    def stop_service(self,request,response):
        self.stop('user_stopped')
        return response

    def stop(self,reason):
        if self.mode!='disabled':
            self.cmd.publish(Twist())
        self.mode='disabled'
        self.epoch+=1
        self.target=None
        self.reason=reason
        self.active.publish(Bool(data=False))

    def detect(self,frame):
        stamp,data=frame
        img=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
        if img is None:
            return stamp,None
        img=cv2.resize(img,(480,360))
        rects,weights=self.hog.detectMultiScale(img,winStride=(8,8),padding=(8,8),scale=1.05)
        boxes=[(x/480,y/360,w/480,h/360) for (x,y,w,h),score in zip(rects,weights) if float(score)>0.7 and h>85]
        return stamp,boxes[0] if len(boxes)==1 else None

    def tick(self):
        now=time.monotonic()
        if now-self.last_report>0.5:
            labels={'disabled':'未开启','pausing':'正在暂停自动任务','arming':'准备跟随',
                    'seeking':'请站在镜头前，等待锁定单一目标','tracking':'正在跟随'}
            reasons={'disabled':'','user_stopped':'已退出','manual_takeover':'手柄已接管',
                     'imu_stale':'IMU数据中断或过期，跟随禁止启动/已退出，请检查传感器',
                     'camera_stale':'相机数据中断或过期，跟随禁止启动/已退出',
                     'arming_timeout':'等待任务或底盘服务超时，已退出',
                     'pause_failed':'暂停任务失败，未启动跟随',
                     'base_resume_failed':'底盘恢复失败，未启动跟随',
                     'inference_stale':'人体检测结果过期，已停车',
                     'mission_changed':'其他任务介入，已退出','no_unique_target':'未找到稳定的单一人体，请重新开启',
                     'target_missing_or_ambiguous':'目标丢失或出现多人，已停车',
                     'target_changed':'目标变化过大，已停车',
                     'obstacle_or_scan_stale':'附近有障碍或雷达数据过期，已停车',
                     'target_or_sensor_stale':'目标或传感器数据过期，已停车',
                     'start_rejected_inputs_not_ready':'相机、雷达或手柄状态不满足开启条件',
                     'start_rejected_services_not_ready':'任务服务尚未就绪'}
            self.status.publish(String(data=json.dumps(dict(mode=self.mode,reason=self.reason,
                message=labels.get(self.mode,self.mode)+'；'+reasons.get(self.reason,self.reason),
                camera_age=round(now-self.frame[0],2) if self.frame else None,
                imu_age=round(now-self.last_imu,2) if self.last_imu is not None else None,
                target=self.target),ensure_ascii=False)))
            self.last_report=now
        if self.mode in ('pausing','arming'):
            if now-self.transition_time>5:
                self.stop('arming_timeout')
            return
        if self.mode=='disabled':
            return
        fault=self.input_fault(now)
        if fault:
            self.stop(fault);return
        if self.future is not None and self.future.done():
            try:
                stamp,box=self.future.result()
            except Exception:
                stamp,box=0,None
            self.future=None
            if self.future_epoch != self.epoch:
                return
            cmd,reason=safe_command(box,self.previous,self.scans,now)
            if now-stamp>0.7 or cmd is None:
                if self.mode=='tracking':
                    self.stop(reason if cmd is None else 'inference_stale');return
                self.stable=0
            else:
                self.previous=box
                self.target=box
                self.target_time=stamp
                self.stable+=1
                if self.stable>=3:
                    self.mode='tracking'
        if self.mode=='seeking' and now-self.seek_since>12:
            self.stop('no_unique_target');return
        cmd,reason=safe_command(self.target,self.previous,self.scans,now)
        if self.mode=='tracking' and (now-self.target_time>0.7 or cmd is None):
            self.stop('target_or_sensor_stale' if cmd else reason);return
        twist=Twist()
        if self.mode=='tracking' and cmd:
            twist.linear.x,twist.angular.z=cmd
        self.cmd.publish(twist)
        self.reason=self.mode
        if self.future is None and self.frame and now-self.frame[0]<0.5 and now-self.last_infer>0.2:
            self.future=self.pool.submit(self.detect,self.frame)
            self.future_epoch=self.epoch
            self.last_infer=now


def main():
    rclpy.init()
    node=PersonFollow()
    try:
        rclpy.spin(node)
    finally:
        node.stop('shutdown') if rclpy.ok() else None
        node.pool.shutdown(wait=False,cancel_futures=True)
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()

if __name__=='__main__':main()
