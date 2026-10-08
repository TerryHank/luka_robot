from launch import LaunchDescription
from launch.actions import TimerAction,ExecuteProcess
from launch_ros.actions import Node

def generate_launch_description():
    nodes=[]
    for name,interface,source,port,frame,topic,inverted in [
        ('upper','eth0','192.168.11.10',28089,'laser','/scan',False),
        ('lower','eth1','192.168.11.11',18089,'laser_low','/scan_low_raw',True)]:
        nodes.append(Node(package='ddsm_car_control',executable='low_lidar_udp_proxy',name='nx_'+name+'_proxy',arguments=['--interface',interface,'--source-ip',source,'--listen-port',str(port)],respawn=True,respawn_delay=5.,output='screen'))
        nodes.append(Node(package='rplidar_ros',executable='rplidar_node',name='nx_'+name+'_lidar',parameters=[dict(channel_type='udp',udp_ip='127.0.0.1',udp_port=port,frame_id=frame,inverted=inverted,angle_compensate=True,scan_mode='Sensitivity',scan_frequency=10.0,topic_name=topic,reconnect_grab_failures=3)],respawn=True,respawn_delay=5.,output='screen'))
    nodes.append(Node(package='ddsm_car_control',executable='wit_imu_node',name='nx_imu',parameters=[dict(port='/dev/nx_imu',baud=921600,protocol='normal',configure_output=False)],output='screen'))
    for frame,x,y,z,yaw in [('laser',-.065,0.,.42,0.),('laser_low',.281,.005,.10,1.56975)]:
        nodes.append(Node(package='tf2_ros',executable='static_transform_publisher',name='nx_tf_'+frame,arguments=['--x',str(x),'--y',str(y),'--z',str(z),'--yaw',str(yaw),'--frame-id','base_link','--child-frame-id',frame]))
    nodes.append(Node(package='ddsm_car_control',executable='dual_laser_fusion',name='dual_laser_fusion',parameters=[dict(primary_topic='/scan',secondary_topic='/scan_low_chassis_filtered',secondary_filtered_topic='/scan_low_filtered',output_topic='/scan_obstacle_fused',secondary_x=.346,secondary_y=.005,secondary_yaw=1.56975,secondary_keep_min_deg=-180.,secondary_keep_max_deg=0.,secondary_self_filter_enabled=True,secondary_self_filter_min_x=-.30,secondary_self_filter_max_x=.30,secondary_self_filter_min_y=-.21,secondary_self_filter_max_y=.21,secondary_timeout=.25,secondary_sync_tolerance=.15,fused_publish_rate=20.)],output='screen'))
    # Only a narrow, measured bracket rectangle is removed before existing fusion.
    # Replace the lower input parameter on the existing fusion action below via
    # its construction (the upper scan and original mask remain unchanged).
    nodes.append(ExecuteProcess(cmd=['python3','/home/sunrise/luka_ws/src/system/runtime/tools/nx_chassis_filter.py'],output='screen'))
    # UDP proxies must bind before the first RPLIDAR handshake is sent.
    proxies=[n for i,n in enumerate(nodes) if i in (0,2)]
    return LaunchDescription(proxies+[TimerAction(period=2.0,actions=[n for i,n in enumerate(nodes) if i not in (0,2)])])
