"""Face-only HTTP/ROS contract using synthetic images and features; no live identity data."""
import json,os,threading,time,urllib.request
from pathlib import Path
import tempfile

os.environ['ROS_DOMAIN_ID']='101'
os.environ['ROS_LOCALHOST_ONLY']='1'
import numpy as np
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from ai_msgs.msg import PerceptionTargets,Target,Roi
from sensor_msgs.msg import Image
from luka_face_identity.node import FaceIdentity


def test_face_reuses_mot_rejects_motion_and_expires_input():
    with tempfile.TemporaryDirectory() as directory:
        rclpy.init(args=['--ros-args','-p','database_path:='+directory+'/test.sqlite3',
                         '-p','http_port:=0'])
        node=FaceIdentity()
        camera=Node('face_contract_camera')
        images=camera.create_publisher(Image,'/camera/color/image_raw',10)
        targets=camera.create_publisher(PerceptionTargets,'/tros_mot_targets',10)
        executor=MultiThreadedExecutor(num_threads=2)
        executor.add_node(node);executor.add_node(camera)
        thread=threading.Thread(target=executor.spin,daemon=True);thread.start()
        vector=np.zeros(128,np.float32);vector[0]=1
        class FakeFace:
            def face_features(self,image,box):
                return {'accepted':True,'embedding':vector,'enrollment_eligible':True,'reason':'ok'}
        node.features=FakeFace()
        port=node.server.server_address[1]
        def request(path,body=None):
            data=None if body is None else json.dumps(body).encode()
            with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:'+str(port)+path,
                    data=data,headers={'Content-Type':'application/json'}),timeout=2) as response:
                return json.load(response)
        try:
            assert request('/api/people/status')['motion_enabled'] is False
            request('/api/people/start',{})
            deadline=time.monotonic()+2
            while time.monotonic()<deadline:
                stamp=camera.get_clock().now().to_msg()
                msg=PerceptionTargets();msg.header.stamp=stamp;msg.header.frame_id='camera_color_optical_frame'
                roi=Roi(type='person',confidence=.95)
                roi.rect.x_offset=200;roi.rect.y_offset=80;roi.rect.width=150;roi.rect.height=300
                msg.targets=[Target(type='person',track_id=42,rois=[roi])]
                targets.publish(msg)
                image=Image();image.header=msg.header;image.width=640;image.height=480
                image.encoding='rgb8';image.step=1920;image.data=bytes(640*480*3)
                images.publish(image);time.sleep(.1)
                if node.tracks:break
            status=request('/api/people/status')
            assert status['tracks'][0]['track_id']==42
            assert status['target_session']['active'] is False
            request('/api/people/select',{'track_id':42})
            assert request('/api/people/status')['selected_track_id']==42
            try:request('/api/people/confirm-target',{'track_id':42,'profile_id':'owner'})
            except urllib.error.HTTPError as error:assert error.code==409
            else:raise AssertionError('Old identity motion authorization must remain retired')
            # MOT stays fresh while the camera stops; old identities must expire.
            deadline=time.monotonic()+.9
            while time.monotonic()<deadline:
                msg.header.stamp=camera.get_clock().now().to_msg()
                targets.publish(msg)
                time.sleep(.1)
            assert request('/api/people/status')['tracks']==[]
            publishers=node.get_publisher_names_and_types_by_node(node.get_name(),node.get_namespace())
            assert all('geometry_msgs/msg/Twist' not in types for _,types in publishers)
            assert all('PerceptionTargets' not in name for name,_ in publishers)
        finally:
            executor.shutdown(timeout_sec=2);node.close();node.destroy_node();camera.destroy_node();rclpy.shutdown()
