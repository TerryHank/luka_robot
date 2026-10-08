"""ROS consumer of the canonical image API; owns neither camera nor BPU model."""
import base64
import json
import threading
import time
import urllib.request
import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import String
from cv_bridge import CvBridge


class MaskStream(Node):
    def __init__(self):
        super().__init__('luka_dynamic_mask')
        self.bridge=CvBridge();self.latest=None;self.lock=threading.Lock()
        self.stop=threading.Event();self.last_stamp=None
        self.state={'state':'waiting_for_rgb','frames':0,'masked_frames':0,'stale_dropped':0}
        self.pub=self.create_publisher(Image,'/perception/dynamic_mask',5)
        self.status=self.create_publisher(String,'/perception/dynamic_mask/status',5)
        self.create_subscription(Image,'/camera/color/image_raw',self.image,qos_profile_sensor_data)
        self.create_timer(1.,self.report)
        self.worker=threading.Thread(target=self.run,daemon=True);self.worker.start()

    def image(self,msg):
        with self.lock:self.latest=msg

    def report(self):
        self.status.publish(String(data=json.dumps(self.state)))

    def run(self):
        while not self.stop.wait(.03):
            with self.lock:msg=self.latest
            if msg is None:continue
            stamp=msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9
            if stamp==self.last_stamp:continue
            self.last_stamp=stamp
            try:
                if not -.05 <= self.get_clock().now().nanoseconds/1e9-stamp <= .6:continue
                image=self.bridge.imgmsg_to_cv2(msg,desired_encoding='bgr8')
                ok,encoded=cv2.imencode('.png',image)
                if not ok:raise ValueError('RGB encoding failed')
                body=json.dumps({'image_base64':base64.b64encode(encoded).decode(),'query':'person'}).encode()
                request=urllib.request.Request('http://127.0.0.1:8096/infer_mask',data=body,headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(request,timeout=30) as response:result=json.load(response)
                age=self.get_clock().now().nanoseconds/1e9-stamp
                if not -.05 <= age <= .6:
                    self.state.update(state='stale_result_dropped',age_s=age,stale_dropped=self.state['stale_dropped']+1)
                    continue
                mask=cv2.imdecode(np.frombuffer(base64.b64decode(result['mask_png_base64']),np.uint8),cv2.IMREAD_UNCHANGED)
                if mask is None or mask.dtype!=np.uint8 or mask.shape!=(msg.height,msg.width):
                    raise ValueError('invalid mask geometry')
                out=self.bridge.cv2_to_imgmsg(mask,encoding='mono8');out.header=msg.header
                if self.stop.is_set():break
                self.pub.publish(out)
                nonzero=int(np.count_nonzero(mask))
                self.state.update(state='publishing',frames=self.state['frames']+1,
                                  masked_frames=self.state['masked_frames']+int(nonzero>0),
                                  people=result['people'],masked_pixels=nonzero,age_s=round(age,4),
                                  inference_s=result['inference_seconds'],source_stamp=stamp)
            except Exception as error:
                self.state.update(state='inference_unavailable',error=type(error).__name__)
                self.stop.wait(.5)


def main():
    rclpy.init();node=MaskStream()
    try:rclpy.spin(node)
    except (KeyboardInterrupt,ExternalShutdownException):pass
    finally:
        node.stop.set();node.worker.join(timeout=31);node.destroy_node()
        if rclpy.ok():rclpy.shutdown()


if __name__=='__main__':main()
