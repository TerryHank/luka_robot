"""VIMS-style layering adapted to Astra RGB-D; production navigation is separate."""
import os
import yaml
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction, SetEnvironmentVariable, LogInfo
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
from luka_visual_slam.contracts import session_database


def setup(context):
    def value(name): return LaunchConfiguration(name).perform(context)
    def flag(name):
        if value(name) not in ('true','false'): raise ValueError(name+' must be true or false')
        return value(name)=='true'
    frontend=value('frontend')
    if frontend not in ('rgbd','external'): raise ValueError('frontend must be rgbd or external')
    filtered=flag('mask_depth')
    # A direct ros2 launch must also reject duplicate owners, not just start.sh.
    import time
    import rclpy
    from rclpy.context import Context
    from rclpy.executors import SingleThreadedExecutor
    ctx=Context();rclpy.init(args=[],context=ctx)
    probe=rclpy.create_node('visual_slam_launch_probe',context=ctx)
    executor=SingleThreadedExecutor(context=ctx);executor.add_node(probe)
    try:
        deadline=time.monotonic()+1.5
        while time.monotonic()<deadline:executor.spin_once(timeout_sec=.1)
        if any(ns=='/rtabmap_rgbd' or ns.startswith('/rtabmap_rgbd/')
               for _,ns in probe.get_node_names_and_namespaces()):
            raise RuntimeError('Visual SLAM namespace is already owned; stop the existing instance first')
        if filtered and not probe.count_publishers(value('mask_topic')):
            raise RuntimeError('mask_depth requires a real aligned mono8 mask publisher: '+value('mask_topic'))
        if frontend=='external' and not probe.count_publishers(value('external_odom_topic')):
            raise RuntimeError('external frontend requires a live nav_msgs/Odometry publisher')
    finally:
        executor.shutdown();probe.destroy_node();rclpy.shutdown(context=ctx)
    database=session_database(value('mode'),value('database_path'),'/home/sunrise/luka_data')
    share=get_package_share_directory('luka_visual_slam')
    def config(name):
        with open(os.path.join(share,'config',name+'.yaml')) as f: return yaml.safe_load(f)
    ns='rtabmap_rgbd'
    common={'frame_id':value('camera_frame'),'publish_tf':True,'approx_sync':True,
            'approx_sync_max_interval':.06,'topic_queue_size':10,'sync_queue_size':20,
            'qos':2,'qos_camera_info':2,'wait_for_transform':.2}
    image_remaps=[('rgb/image',value('rgb_topic')),('depth/image',value('depth_topic')),
                  ('rgb/camera_info',value('camera_info_topic')),('/tf','/rtabmap_rgbd/tf')]
    nodes=[LogInfo(msg='Visual SLAM '+value('mode')+' database: '+database)]
    if frontend=='rgbd':
        nodes.append(Node(package='rtabmap_odom',executable='rgbd_odometry',name='rgbd_odometry',
                          namespace=ns,output='screen',parameters=[common,config('frontend'),
                          {'odom_frame_id':'rtabmap_rgbd_odom'}],remappings=image_remaps))
    if filtered:
        nodes.append(Node(package='luka_visual_slam',executable='depth_filter.py',namespace=ns,
                          output='screen',remappings=[('rgb',value('rgb_topic')),('depth',value('depth_topic')),
                          ('camera_info',value('camera_info_topic')),('dynamic_mask',value('mask_topic'))]))
    backend_images=image_remaps if not filtered else [
        ('rgb/image','filtered/rgb'),('depth/image','filtered/depth'),
        ('rgb/camera_info','filtered/camera_info'),('/tf','/rtabmap_rgbd/tf')]
    nodes.append(Node(package='rtabmap_slam',executable='rtabmap',name='rtabmap',namespace=ns,
                      output='screen',parameters=[common,config('backend'),
                      {'subscribe_depth':True,'subscribe_rgb':True,'database_path':database,
                       'odom_frame_id':'rtabmap_rgbd_odom' if frontend=='rgbd' else '',
                       'map_frame_id':'rtabmap_rgbd_map',
                       'Mem/IncrementalMemory':'true' if value('mode')=='mapping' else 'false',
                       'Mem/InitWMWithAllNodes':'true' if value('mode')=='localization' else 'false'}],
                      remappings=backend_images+[('odom','odom' if frontend=='rgbd' else value('external_odom_topic'))]))
    if flag('planning_preview'):
        if frontend!='rgbd': raise ValueError('planning preview currently requires the private RGB-D TF chain')
        nodes += [Node(package='nav2_planner',executable='planner_server',name='planner_server',
                       namespace=ns,output='screen',parameters=[os.path.join(share,'config','nav2_preview.yaml')],
                       remappings=[('/tf','/rtabmap_rgbd/tf'),('map','/rtabmap_rgbd/map')]),
                  Node(package='nav2_lifecycle_manager',executable='lifecycle_manager',
                       name='planning_lifecycle',namespace=ns,output='screen',
                       parameters=[{'autostart':True,'node_names':['planner_server']}])]
    return nodes


def generate_launch_description():
    args={'mode':'mapping','database_path':'','frontend':'rgbd','external_odom_topic':'/visual_odometry/odom',
          'camera_frame':'camera_link','rgb_topic':'/camera/color/image_raw',
          'depth_topic':'/camera/depth/image_raw','camera_info_topic':'/camera/color/camera_info',
          'mask_depth':'false','mask_topic':'/perception/dynamic_mask','planning_preview':'false'}
    return LaunchDescription([DeclareLaunchArgument(k,default_value=v) for k,v in args.items()]+
        [SetEnvironmentVariable('OMP_NUM_THREADS','2'),SetEnvironmentVariable('OPENBLAS_NUM_THREADS','1'),
         OpaqueFunction(function=setup)])
