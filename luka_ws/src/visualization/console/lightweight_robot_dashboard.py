#!/usr/bin/env python3
import json
import math
import os
import signal
import threading
import time
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path as FsPath

import cv2
import numpy as np
import rclpy
import yaml
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import OccupancyGrid, Odometry, Path
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String
from tf2_msgs.msg import TFMessage
from robot_diagnostics import RobotDiagnostics
from std_srvs.srv import Empty as EmptyService


HTML = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Robot Monitor</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; background: #0d1117; color: #d8dee9; font: 14px Arial, sans-serif; }
    header { min-height: 48px; display: flex; align-items: center; gap: 12px; padding: 7px 18px; border-bottom: 1px solid #29313d; flex-wrap: wrap; }
    header strong { font-size: 17px; }
    #status { color: #8b949e; }
    header .spacer { flex: 1; }
    main { height: calc(100vh - 56px); display: grid; grid-template-columns: minmax(0, 1fr) 340px; }
    #stage { position: relative; overflow: hidden; background: #080b10; }
    canvas { width: 100%; height: 100%; display: block; }
    aside { border-left: 1px solid #29313d; padding: 14px; overflow: auto; }
    .panel { margin-bottom: 12px; padding: 12px; border: 1px solid #29313d; border-radius: 6px; background: #151b23; }
    .panel h2 { margin: 0 0 10px; font-size: 14px; }
    .row { display: flex; justify-content: space-between; margin: 7px 0; color: #9da7b3; }
    .row b { color: #e6edf3; font-weight: 500; }
    .ok { color: #56d364 !important; } .warn { color: #e3b341 !important; } .bad { color: #f85149 !important; }
    #camera { width: 100%; min-height: 120px; object-fit: contain; background: #080b10; }
    button { border: 1px solid #3d4857; background: #212936; color: #e6edf3; padding: 7px 11px; border-radius: 4px; cursor: pointer; }
    button.primary { background: #1f6feb; border-color: #388bfd; }
    button.danger { background: #6e1b22; border-color: #b6232e; }
    button.go { padding: 4px 9px; font-size: 12px; background: #1f6feb; border-color: #388bfd; white-space: nowrap; }
    select { border: 1px solid #3d4857; background: #212936; color: #e6edf3; padding: 7px 8px; border-radius: 4px; max-width: 240px; }
    label.toggle { color: #9da7b3; white-space: nowrap; }
    input:not([type="checkbox"]) { width: 100%; border: 1px solid #3d4857; background: #0d1117; color: #e6edf3; padding: 8px; border-radius: 4px; }
    input[type="checkbox"] { width: auto; margin: 0 4px 0 0; vertical-align: middle; }
    .form-grid { display: grid; grid-template-columns: 1fr 86px; gap: 8px; margin-bottom: 8px; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; }
    #pickInfo { color: #9da7b3; margin: 8px 0; font-size: 12px; }
    #waypointList { max-height: 180px; overflow: auto; }
    .waypoint { display: grid; grid-template-columns: 1fr auto; gap: 8px; padding: 7px 0; border-top: 1px solid #29313d; }
    .waypoint small { color: #8b949e; }
    .llm-log { max-height: 240px; overflow: auto; margin-top: 8px; font: 12px/1.6 Consolas, Monaco, monospace; color: #9da7b3; }
    .llm-line { white-space: pre-wrap; word-break: break-all; }
    .llm-line.me { color: #7c9cf5; }
    .llm-line.ok { color: #56d364; }
    .llm-line.warn { color: #e3b341; }
    .llm-line.bad { color: #f85149; }
    @media (max-width: 850px) { main { grid-template-columns: 1fr; grid-template-rows: 68vh auto; } aside { border-left: 0; border-top: 1px solid #29313d; } }
  </style>
</head>
<body>
<header><strong>Robot Monitor</strong><span id="status">正在连接...</span><span class="spacer"></span>
  <label class="toggle"><input id="showWaypoints" type="checkbox" checked> 航点</label>
  <select id="navMode" title="选择自动导航的车体运动方式">
    <option value="omni">全向模式（允许斜行）</option>
    <option value="forward_facing">车头朝向模式（禁止斜行）</option>
  </select>
  <select id="mapSelect" title="选择地图（航点将保存到对应楼层）"><option value="">跟随实车（导航栈地图）</option></select>
  <button id="fit">适配地图</button><button id="shutdown" class="danger">关闭监控</button>
</header>
<main>
  <section id="stage"><canvas id="view"></canvas></section>
  <aside>
    <div class="panel"><h2>视觉跟随（试验版）</h2><p>站在镜头前，仅保留一人。采用人体画面大小控制，不代表精确距离。丢失目标后需重新开启。</p><button id="followStart">开启跟随</button> <button id="followStop">退出跟随</button><div id="followStatus">未启动</div><small>退出后不会自动恢复旧任务；可重新指定目的地，或明确恢复旧任务。</small></div>
    <div class="panel"><h2>最近导航请求反馈</h2><div id="missionGoalStatus">暂无反馈</div></div>
    <div class="panel"><h2>运行健康检查</h2><div id="healthChecks">等待检查</div><div id="lastIncident" style="overflow-wrap:anywhere;color:#9da7b3;margin-top:10px"></div><a href="/api/incidents" target="_blank" style="color:#79b8ff">查看历史故障记录</a></div>
    <div class="panel"><h2>数据状态</h2>
      <div class="row"><span>地图</span><b id="mapAge">--</b></div>
      <div class="row"><span>位姿</span><b id="poseAge">--</b></div>
      <div class="row"><span>融合雷达</span><b id="scanAge">--</b></div>
      <div class="row"><span>路径</span><b id="pathCount">--</b></div>
      <div class="row"><span>当前地图</span><b id="curMap">--</b></div>
      <div class="row"><span>当前楼层</span><b id="floorId">--</b></div>
    </div>
    <div class="panel"><h2>机器人位姿</h2>
      <div class="row"><span>X</span><b id="x">--</b></div>
      <div class="row"><span>Y</span><b id="y">--</b></div>
      <div class="row"><span>Yaw</span><b id="yaw">--</b></div>
    </div>
    <div class="panel"><h2>新增航点</h2>
      <div class="form-grid"><input id="wpName" placeholder="航点名称"><input id="wpYaw" type="number" value="0" step="1" placeholder="角度"></div>
      <div id="pickInfo">点击“地图选点”，再在地图上点击位置</div>
      <div class="actions"><button id="pick">地图选点</button><button id="saveWp" class="primary">保存航点</button></div>
    </div>
    <div class="panel"><h2>大模型指令</h2>
      <input id="llmInput" placeholder="如：去厨房 / 回充电点 / 去卧室 / 去浴室 / 停止">
      <div class="actions" style="margin-top:8px"><button id="llmSendBtn" class="primary">发送</button><button id="llmClearBtn">清空</button></div>
      <div id="llmLog" class="llm-log"><div class="llm-line">（指令会经 nav_llm_agent → 板上 Qwen2.5 解析 → 真车导航）</div></div>
    </div>
    <div class="panel"><h2>当前楼层航点</h2><div id="waypointList">暂无航点</div></div>
    <div class="panel"><h2>视觉识别</h2><img id="camera" alt="视觉节点未输出"></div>
  </aside>
</main>
<script>
const canvas = document.getElementById('view'), ctx = canvas.getContext('2d');
const xEl = document.getElementById('x'), yEl = document.getElementById('y'), yawEl = document.getElementById('yaw');
const mapImg = new Image();
let state = null, fitted = false, scale = 1, ox = 0, oy = 0, mapVersion = -1, picking = false, selected = null;
function resize(){ const r=canvas.getBoundingClientRect(), d=devicePixelRatio||1; canvas.width=r.width*d; canvas.height=r.height*d; ctx.setTransform(d,0,0,d,0,0); if(!fitted) fit(); draw(); }
function fit(){ if(!state || !state.map.width) return; const w=canvas.clientWidth,h=canvas.clientHeight,m=24; scale=Math.min((w-2*m)/state.map.width,(h-2*m)/state.map.height); ox=(w-state.map.width*scale)/2; oy=(h-state.map.height*scale)/2; fitted=true; draw(); }
function localPoint(x,y){ const m=state.map, dx=x-m.origin_x,dy=y-m.origin_y,c=Math.cos(-m.origin_yaw),s=Math.sin(-m.origin_yaw); return [dx*c-dy*s,dx*s+dy*c]; }
function pixel(x,y){ const p=localPoint(x,y),m=state.map; return [ox+p[0]/m.resolution*scale,oy+(m.height-p[1]/m.resolution)*scale]; }
function worldPoint(sx,sy){ const m=state.map,px=(sx-ox)/scale,py=(sy-oy)/scale,lx=px*m.resolution,ly=(m.height-py)*m.resolution,c=Math.cos(m.origin_yaw),s=Math.sin(m.origin_yaw);return [m.origin_x+c*lx-s*ly,m.origin_y+s*lx+c*ly]; }
function ageClass(v){ return v < 0 ? 'bad' : v < 1 ? 'ok' : v < 3 ? 'warn' : 'bad'; }
function setAge(id,v){ const e=document.getElementById(id); e.className=ageClass(v); e.textContent=v<0?'无数据':v.toFixed(1)+' s'; }
function draw(){
  const w=canvas.clientWidth,h=canvas.clientHeight; ctx.clearRect(0,0,w,h); if(!state||!state.map.width) return;
  ctx.imageSmoothingEnabled=false; if(mapImg.complete && mapImg.naturalWidth) ctx.drawImage(mapImg,ox,oy,state.map.width*scale,state.map.height*scale);
  const path=state.path||[]; if(path.length){ ctx.strokeStyle='#7c6cff';ctx.lineWidth=3;ctx.beginPath();path.forEach((p,i)=>{const q=pixel(p[0],p[1]);i?ctx.lineTo(...q):ctx.moveTo(...q)});ctx.stroke(); }
  if(document.getElementById('showWaypoints').checked){ ctx.font='10px Arial'; for(const p of state.waypoints||[]){const q=pixel(p.x,p.y);ctx.fillStyle='#ec4899';ctx.beginPath();ctx.arc(q[0],q[1],5,0,Math.PI*2);ctx.fill();ctx.fillStyle='#ff4d4f';ctx.fillText(p.display_name||p.id,q[0]+8,q[1]-7);} }
  if(selected){const q=pixel(selected[0],selected[1]);ctx.strokeStyle='#fbbf24';ctx.lineWidth=2;ctx.beginPath();ctx.arc(q[0],q[1],8,0,Math.PI*2);ctx.stroke();}
  const r=state.pose; if(!r) return;
  ctx.fillStyle='#2dd4bf'; for(const p of state.scan||[]){ const c=Math.cos(r.yaw),s=Math.sin(r.yaw),wx=r.x+c*p[0]-s*p[1],wy=r.y+s*p[0]+c*p[1],q=pixel(wx,wy);ctx.fillRect(q[0]-1,q[1]-1,2,2); }
  const q=pixel(r.x,r.y),len=24,wid=16; ctx.save();ctx.translate(q[0],q[1]);ctx.rotate(-r.yaw+state.map.origin_yaw);ctx.fillStyle='#7c6cff';ctx.strokeStyle='#fff';ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(len,0);ctx.lineTo(-len*.65,wid);ctx.lineTo(-len*.65,-wid);ctx.closePath();ctx.fill();ctx.stroke();ctx.restore();
}
function renderWaypoints(){const box=document.getElementById('waypointList'),items=state&&state.waypoints||[];box.innerHTML=items.length?items.map(p=>`<div class="waypoint"><span>${p.display_name||p.id}<br><small>${p.id}</small></span><small>${p.x.toFixed(2)}, ${p.y.toFixed(2)}</small><button class="go" data-id="${p.id}">前往</button></div>`).join(''):'暂无航点';}
document.getElementById('waypointList').onclick=async ev=>{const btn=ev.target.closest('button.go');if(!btn)return;if(!confirm(`发送航点 ${btn.dataset.id}？小车将移动！`))return;btn.disabled=true;try{const res=await fetch('/api/nav',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:btn.dataset.id})});const body=await res.json();if(!res.ok){alert(body.error||'发送失败');return;}document.getElementById('pickInfo').textContent=`已发送 ${body.display_name}（${body.id}）→ ${body.floor_id}`;}finally{btn.disabled=false;}};
document.getElementById('fit').onclick=()=>{fitted=false;fit()};
document.getElementById('showWaypoints').onchange=draw;
document.getElementById('pick').onclick=()=>{picking=true;selected=null;document.getElementById('pickInfo').textContent='请在地图上点击航点位置';};
canvas.addEventListener('click',ev=>{if(!picking||!state||!state.map.width)return;const r=canvas.getBoundingClientRect();selected=worldPoint(ev.clientX-r.left,ev.clientY-r.top);picking=false;document.getElementById('pickInfo').textContent=`位置：${selected[0].toFixed(3)}, ${selected[1].toFixed(3)}`;draw();});
document.getElementById('saveWp').onclick=async()=>{const name=document.getElementById('wpName').value.trim();if(!selected){alert('请先在地图上选点');return;}if(!name){alert('请输入航点名称');return;}const yaw=Number(document.getElementById('wpYaw').value||0)*Math.PI/180;const res=await fetch('/api/waypoints',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({display_name:name,x:selected[0],y:selected[1],yaw})});const body=await res.json();if(!res.ok){alert(body.error||'保存失败');return;}document.getElementById('pickInfo').textContent=`已保存 ${body.id}：${name}`;document.getElementById('wpName').value='';selected=null;};
document.getElementById('shutdown').onclick=async()=>{if(!confirm('关闭轻量监控页面？导航节点不会受影响。'))return;await fetch('/api/shutdown',{method:'POST'});document.getElementById('status').textContent='监控已关闭';};
const mapSelect=document.getElementById('mapSelect');
const navMode=document.getElementById('navMode');
navMode.onchange=async()=>{navMode.disabled=true;try{const res=await fetch('/api/nav/mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:navMode.value})});const body=await res.json();if(!res.ok){alert(body.error||'导航模式切换失败');navMode.value=state&&state.navigation_mode||'omni';}else{navMode.value=body.mode;}}finally{navMode.disabled=false;}};
mapSelect.onchange=async()=>{const v=mapSelect.value||null;const res=await fetch('/api/map/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({map_id:v})});const body=await res.json();if(!res.ok){alert(body.error||'切换地图失败');mapSelect.value=state&&state.selected_map||'';}else{mapSelect.value=body.selected_map||'';} };
const llmLog=document.getElementById('llmLog');let llmCount=0;
async function llmSend(){const inp=document.getElementById('llmInput');const t=inp.value.trim();if(!t)return;inp.value='';const res=await fetch('/api/llm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:t})});const body=await res.json();if(!res.ok){alert(body.error||'发送失败');}}
function renderLLMLog(log){if(!log||log.length<=llmCount)return;const frag=document.createDocumentFragment();for(let i=llmCount;i<log.length;i++){const e=log[i],d=document.createElement('div');d.className='llm-line '+(e.cls||'');d.textContent=(e.t||'')+' '+(e.msg||'');frag.appendChild(d);}llmCount=log.length;const near=llmLog.scrollTop+llmLog.clientHeight>=llmLog.scrollHeight-40;llmLog.appendChild(frag);if(near)llmLog.scrollTop=llmLog.scrollHeight;}
document.getElementById('llmSendBtn').onclick=llmSend;
document.getElementById('llmInput').addEventListener('keydown',ev=>{if(ev.key==='Enter')llmSend();});
document.getElementById('llmClearBtn').onclick=()=>{llmLog.innerHTML='';llmCount=0;};
window.addEventListener('resize',resize);
const events=new EventSource('/events');
for(const [id,action] of [['followStart','start'],['followStop','stop']]){document.getElementById(id).onclick=async()=>{const response=await fetch('/api/follow/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(!response.ok)alert('跟随服务未就绪');};}
events.onopen=()=>{document.getElementById('status').textContent='已连接'};
events.onerror=()=>{document.getElementById('status').textContent='连接中断，正在重连'};
events.onmessage=(ev)=>{ state=JSON.parse(ev.data);
  try{const follow=JSON.parse(state.follow_status||'{}');document.getElementById('followStatus').textContent=follow.message||follow.mode||'未收到跟随状态';}catch{document.getElementById('followStatus').textContent='等待跟随状态';}
  try{const goal=JSON.parse(state.mission_goal_status||'{}');document.getElementById('missionGoalStatus').textContent=goal.message||'暂无反馈';}catch{}
  const healthBox=document.getElementById('healthChecks');healthBox.replaceChildren();
  for(const check of state.diagnostics?.checks||[]){const row=document.createElement('div');row.className=check.ok===true?'ok':check.ok===false?'bad':'warn';row.style.marginBottom='7px';row.textContent=check.label+'：'+check.detail;healthBox.appendChild(row);}
  const incident=state.diagnostics?.latest_incident;document.getElementById('lastIncident').textContent=incident?'最近故障记录：'+incident.status+' '+(incident.summary||''):'本次启动尚无故障记录';
  navMode.value=state.navigation_mode||'omni';
  if(state.maps&&mapSelect.options.length<=1){for(const m of state.maps){const o=document.createElement('option');o.value=m.id;o.textContent=m.name;mapSelect.appendChild(o);} }
  if(state.selected_map){mapSelect.value=state.selected_map;}else{mapSelect.value='';}
  renderLLMLog(state.llm_log||[]);
  const curMap=document.getElementById('curMap');curMap.textContent=state.selected_map?(state.maps||[]).find(m=>m.id===state.selected_map)?.name||state.selected_map:'跟随实车';
  if(state.map.version!==mapVersion){mapVersion=state.map.version;fitted=false;mapImg.src='/map.png?v='+mapVersion;mapImg.onload=()=>{if(!fitted)fit();draw()};} const mapAge=document.getElementById('mapAge');mapAge.textContent=state.map.width?'已加载':'无数据';mapAge.className=state.map.width?'ok':'bad';setAge('poseAge',state.age.pose);setAge('scanAge',state.age.scan);document.getElementById('pathCount').textContent=(state.path||[]).length+' 点';document.getElementById('floorId').textContent=state.floor_id||'--';if(state.pose){xEl.textContent=state.pose.x.toFixed(3);yEl.textContent=state.pose.y.toFixed(3);yawEl.textContent=(state.pose.yaw*180/Math.PI).toFixed(1)+'°';}renderWaypoints();draw(); };
setInterval(()=>{document.getElementById('camera').src='/camera.jpg?t='+Date.now()},1000);
resize();
</script></body></html>'''


def yaw_from_quaternion(q):
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def compose_planar(first, second):
    """Compose A->B and B->C into A->C."""
    x1, y1, yaw1 = first
    x2, y2, yaw2 = second
    c, s = math.cos(yaw1), math.sin(yaw1)
    return x1 + c*x2 - s*y2, y1 + s*x2 + c*y2, math.atan2(math.sin(yaw1+yaw2), math.cos(yaw1+yaw2))


def inverse_planar(transform):
    x, y, yaw = transform
    c, s = math.cos(yaw), math.sin(yaw)
    return -c*x - s*y, s*x - c*y, -yaw


class DashboardNode(Node):
    def __init__(self):
        super().__init__('lightweight_robot_dashboard')
        self.lock = threading.Lock()
        self.poi_lock = threading.Lock()
        self.transforms = {}
        self.last_scan_process = 0.0
        self.current_odom = None
        self.anchor_map = None
        self.anchor_odom = None
        self.map_png = b''
        self.map_info = {'version': 0, 'width': 0, 'height': 0, 'resolution': 0.05,
                         'origin_x': 0.0, 'origin_y': 0.0, 'origin_yaw': 0.0}
        self.pose = None
        self.scan = []
        self.path = []
        self.last = {'map': 0.0, 'pose': 0.0, 'scan': 0.0}
        self.workspace = FsPath(os.environ.get('DDSM_WS', str(FsPath.home() / 'ddsm_car_ws')))
        self.current_floor_id = os.environ.get('DASHBOARD_FLOOR_ID', '').strip()
        if not self.current_floor_id:
            try:
                context = json.loads((self.workspace / 'common/config' / 'active_floor_context.json').read_text())
                floor_id = context.get('floor_id', '')
                self.current_floor_id = floor_id if re.fullmatch(r'floor_[0-9]+', floor_id) else 'unknown'
            except (OSError, ValueError, TypeError):
                self.current_floor_id = 'unknown'
        self.selected_map = None          # map_id 或 None（None=跟随实车 /map 话题）
        self.map_mode = 'live'            # 'live' | 'file'
        self.available_maps = self.list_maps()
        self.scan_topic = os.environ.get('SCAN_TOPIC', '/scan_obstacle_fused')
        self.poi_cache = []
        self.poi_cache_key = None
        map_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                             durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(OccupancyGrid, '/map', self.on_map, map_qos)
        self.create_subscription(LaserScan, self.scan_topic, self.on_scan, qos_profile_sensor_data)
        self.create_subscription(Odometry, '/odometry/filtered', self.on_odom, qos_profile_sensor_data)
        amcl_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                              durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(PoseWithCovarianceStamped, '/amcl_pose', self.on_amcl, amcl_qos)
        self.create_subscription(Path, '/plan_smoothed', self.on_path, 1)
        self.create_subscription(Path, '/plan', self.on_path, 1)
        tf_static_qos = QoSProfile(depth=100, reliability=ReliabilityPolicy.RELIABLE,
                                   durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(TFMessage, '/tf_static', self.on_tf, tf_static_qos)
        floor_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                               durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(String, '/hotel/floor_mission/status', self.on_floor_status, floor_qos)
        # 发送航点：发到 /hotel/goal_destination，由 ddsm_mission_control 转发命名导航
        self._goal_pub = self.create_publisher(String, '/hotel/goal_destination', 10)
        mode_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                              durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.navigation_mode_file = self.workspace / 'common/config' / 'navigation_motion_mode.txt'
        try:
            saved_navigation_mode = self.navigation_mode_file.read_text(encoding='utf-8').strip()
        except OSError:
            saved_navigation_mode = ''
        self.navigation_mode = (
            saved_navigation_mode
            or os.environ.get('NAVIGATION_MOTION_MODE', 'omni')
        ).strip().lower()
        if self.navigation_mode not in ('omni', 'forward_facing'):
            self.navigation_mode = 'omni'
        self._motion_mode_pub = self.create_publisher(
            String, '/navigation/motion_mode', mode_qos
        )
        self.publish_navigation_mode()
        # 大模型指令：发布 /llm_command，订阅 /llm_status 做聊天记录
        self._llm_cmd_pub = self.create_publisher(String, '/llm_command', 10)
        self.create_subscription(String, '/llm_status', self.on_llm_status, 10)
        self.llm_log = []
        self.llm_log_max = 100
        self.diagnostics = RobotDiagnostics(self)
        self.follow_status = ''
        self.mission_goal_status = ''
        self.create_subscription(String, '/hotel/mission/goal_status', self.on_mission_goal_status, 10)
        self.create_subscription(String, '/hotel/mission/safety_status', self.on_mission_goal_status, 10)
        self.follow_clients = {action:self.create_client(EmptyService, '/person_follow/'+action) for action in ('start','stop')}
        self.create_subscription(String, '/person_follow/status', self.on_follow_status, 10)

    def on_follow_status(self, msg):
        self.follow_status = msg.data

    def on_mission_goal_status(self, msg):
        self.mission_goal_status = msg.data

    def on_map(self, msg):
        if self.map_mode == 'file':
            return
        grid = np.asarray(msg.data, dtype=np.int16).reshape(msg.info.height, msg.info.width)
        image = np.full(grid.shape, 205, dtype=np.uint8)
        image[grid == 0] = 254
        image[grid >= 50] = 0
        image = cv2.flip(image, 0)
        ok, encoded = cv2.imencode('.png', image, [cv2.IMWRITE_PNG_COMPRESSION, 3])
        if not ok:
            return
        with self.lock:
            self.map_png = encoded.tobytes()
            self.map_info = {
                'version': self.map_info['version'] + 1,
                'width': int(msg.info.width), 'height': int(msg.info.height),
                'resolution': float(msg.info.resolution),
                'origin_x': float(msg.info.origin.position.x),
                'origin_y': float(msg.info.origin.position.y),
                'origin_yaw': yaw_from_quaternion(msg.info.origin.orientation),
            }
            self.last['map'] = time.monotonic()

    def on_scan(self, msg):
        now = time.monotonic()
        if now - self.last_scan_process < 0.2:
            return
        self.last_scan_process = now
        count = len(msg.ranges)
        if count == 0:
            return
        stride = max(1, count // 360)
        indices = np.arange(0, count, stride, dtype=np.int32)
        ranges = np.asarray(msg.ranges, dtype=np.float32)[indices]
        valid = (
            np.isfinite(ranges)
            & (ranges >= msg.range_min)
            & (ranges <= min(msg.range_max, 12.0))
        )
        ranges = ranges[valid]
        angles = msg.angle_min + indices[valid] * msg.angle_increment
        points = np.column_stack((ranges * np.cos(angles), ranges * np.sin(angles)))
        transform = self.lookup_planar('base_link', msg.header.frame_id)
        if transform and points.size:
            tx, ty, tyaw = transform
            c, s = math.cos(tyaw), math.sin(tyaw)
            x = points[:, 0].copy()
            y = points[:, 1]
            points[:, 0] = tx + c * x - s * y
            points[:, 1] = ty + s * x + c * y
        points = np.round(points, 3).tolist()
        with self.lock:
            self.scan = points
            self.last['scan'] = time.monotonic()

    def on_path(self, msg):
        poses = msg.poses
        stride = max(1, len(poses) // 300)
        with self.lock:
            self.path = [[round(p.pose.position.x, 3), round(p.pose.position.y, 3)] for p in poses[::stride]]

    def on_tf(self, msg):
        for tf in msg.transforms:
            parent = tf.header.frame_id.lstrip('/')
            child = tf.child_frame_id.lstrip('/')
            if not parent or not child:
                continue
            self.transforms[(parent, child)] = (
                float(tf.transform.translation.x),
                float(tf.transform.translation.y),
                yaw_from_quaternion(tf.transform.rotation),
            )

    def on_floor_status(self, msg):
        if self.selected_map is not None:
            return
        try:
            payload = json.loads(msg.data)
        except (TypeError, ValueError):
            payload = {'floor_id': msg.data.strip()}
        floor_id = next((payload.get(key) for key in
                         ('current_floor_id', 'current_floor', 'floor_id', 'active_floor')
                         if payload.get(key)), None)
        if isinstance(floor_id, str) and floor_id.startswith('floor_'):
            self.current_floor_id = floor_id

    def list_maps(self):
        """枚举可选地图：maps/ 下的楼层图（ddsm_map_floor_N.yaml）。
        默认图 ddsm_map.yaml 若与某楼层图同一 PGM 则跳过，否则作为 'default' 列出。"""
        maps_dir = self.workspace / 'map/maps'
        entries = []
        if maps_dir.is_dir():
            for yaml_path in sorted(maps_dir.glob('ddsm_map_floor_*.yaml')):
                floor_id = 'floor_' + yaml_path.stem.rsplit('_', 1)[-1]
                entries.append({
                    'id': floor_id,
                    'name': f'楼层{floor_id[-1]}（{yaml_path.name}）',
                    'floor_id': floor_id,
                    'map_file': str(yaml_path),
                })
            base = maps_dir / 'ddsm_map.yaml'
            base_pgm = maps_dir / 'ddsm_map.pgm'
            if base.exists() and base_pgm.exists():
                duplicate = any(
                    FsPath(e['map_file']).with_suffix('.pgm').exists()
                    and FsPath(e['map_file']).with_suffix('.pgm').read_bytes() == base_pgm.read_bytes()
                    for e in entries)
                if not duplicate:
                    entries.insert(0, {
                        'id': 'default',
                        'name': '默认图（ddsm_map）',
                        'floor_id': 'default',
                        'map_file': str(base),
                    })
        return entries

    def select_map(self, map_id):
        """切换地图：None=跟随实车（ROS /map 话题）；否则从文件加载并切换楼层。"""
        if not map_id:
            with self.lock:
                self.selected_map = None
                self.map_mode = 'live'
            self.poi_cache_key = None
            return {'ok': True, 'selected_map': None, 'floor_id': self.current_floor_id}
        entry = next((m for m in self.available_maps if m['id'] == map_id), None)
        if entry is None:
            raise ValueError(f'未知地图: {map_id}')
        map_file = FsPath(entry['map_file'])
        try:
            doc = yaml.safe_load(map_file.read_text(encoding='utf-8')) or {}
            image_file = FsPath(doc['image'])
            if not image_file.is_absolute():
                image_file = map_file.parent / image_file
            negate = bool(doc.get('negate', 0))
            occ_th = float(doc.get('occupied_thresh', 0.65))
            free_th = float(doc.get('free_thresh', 0.25))
            img = cv2.imread(str(image_file), cv2.IMREAD_GRAYSCALE)
            if img is None:
                raise ValueError(f'无法读取地图图像: {image_file}')
            if negate:
                img = 255 - img
            occ = (255 - img.astype(np.float32)) / 255.0
            display = np.full(img.shape, 205, dtype=np.uint8)
            display[occ > occ_th] = 0
            display[occ < free_th] = 254
            ok, encoded = cv2.imencode('.png', display, [cv2.IMWRITE_PNG_COMPRESSION, 3])
            if not ok:
                raise ValueError('地图 PNG 渲染失败')
            origin = doc.get('origin') or [0.0, 0.0, 0.0]
            with self.lock:
                self.map_png = encoded.tobytes()
                self.map_info = {
                    'version': self.map_info['version'] + 1,
                    'width': int(img.shape[1]),
                    'height': int(img.shape[0]),
                    'resolution': float(doc.get('resolution', 0.05)),
                    'origin_x': float(origin[0]),
                    'origin_y': float(origin[1]),
                    'origin_yaw': float(origin[2]) if len(origin) > 2 else 0.0,
                }
                self.last['map'] = time.monotonic()
                self.selected_map = map_id
                self.map_mode = 'file'
            self.current_floor_id = entry['floor_id']
            self.poi_cache_key = None
            return {'ok': True, 'selected_map': map_id, 'floor_id': self.current_floor_id,
                    'map_file': entry['map_file']}
        except (OSError, yaml.YAMLError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f'地图加载失败: {exc}')

    def on_amcl(self, msg):
        p = msg.pose.pose
        self.anchor_map = (float(p.position.x), float(p.position.y), yaw_from_quaternion(p.orientation))
        self.anchor_odom = self.current_odom
        self.set_pose(self.anchor_map)

    def on_odom(self, msg):
        p = msg.pose.pose
        self.current_odom = (float(p.position.x), float(p.position.y), yaw_from_quaternion(p.orientation))
        if self.anchor_map is not None and self.anchor_odom is None:
            self.anchor_odom = self.current_odom
        if self.anchor_map is not None and self.anchor_odom is not None:
            delta = compose_planar(inverse_planar(self.anchor_odom), self.current_odom)
            self.set_pose(compose_planar(self.anchor_map, delta))

    def set_pose(self, transform):
        x, y, yaw = transform
        with self.lock:
            self.pose = {'x': round(x, 4), 'y': round(y, 4), 'yaw': round(yaw, 5)}
            self.last['pose'] = time.monotonic()

    def lookup_planar(self, source, target):
        source, target = source.lstrip('/'), target.lstrip('/')
        if source == target:
            return 0.0, 0.0, 0.0
        queue = [(source, (0.0, 0.0, 0.0))]
        visited = {source}
        while queue:
            frame, accumulated = queue.pop(0)
            for (parent, child), transform in tuple(self.transforms.items()):
                if parent == frame and child not in visited:
                    next_transform = compose_planar(accumulated, transform)
                    if child == target:
                        return next_transform
                    visited.add(child)
                    queue.append((child, next_transform))
                elif child == frame and parent not in visited:
                    next_transform = compose_planar(accumulated, inverse_planar(transform))
                    if parent == target:
                        return next_transform
                    visited.add(parent)
                    queue.append((parent, next_transform))
        return None

    def poi_file(self, create=False):
        candidates = (
            self.workspace / 'common/config' / 'semantic' / self.current_floor_id / 'pois.yaml',
            self.workspace / 'semantic' / self.current_floor_id / 'pois.yaml',
        )
        path = next((item for item in candidates if item.exists()), candidates[0])
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def load_waypoints(self):
        path = self.poi_file()
        try:
            key = (self.current_floor_id, path.stat().st_mtime_ns)
        except FileNotFoundError:
            key = (self.current_floor_id, 0)
        with self.poi_lock:
            if key == self.poi_cache_key:
                return list(self.poi_cache)
            try:
                document = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
            except (OSError, yaml.YAMLError):
                document = {}
            pois = document.get('pois', []) if isinstance(document, dict) else []
            loaded = []
            for item in pois:
                if not isinstance(item, dict) or not item.get('enabled', True):
                    continue
                try:
                    loaded.append({
                        'id': str(item.get('id', '')),
                        'display_name': str(item.get('display_name', item.get('id', ''))),
                        'x': float(item['x']), 'y': float(item['y']),
                        'yaw': float(item.get('yaw', 0.0)),
                    })
                except (KeyError, TypeError, ValueError):
                    continue
            self.poi_cache = loaded
            self.poi_cache_key = key
            return list(self.poi_cache)

    def floor_map_version(self, floor_id):
        """该楼层语义地图的 map_version（来自 map_manifest.yaml），
        新增 POI 必须与之一致，否则语义服务校验失败导致整图不可用。"""
        manifest = self.workspace / 'common/config' / 'semantic' / floor_id / 'map_manifest.yaml'
        try:
            doc = yaml.safe_load(manifest.read_text(encoding='utf-8')) or {}
            version = str(doc.get('map_version') or '').strip()
            if version:
                return version
        except (OSError, yaml.YAMLError):
            pass
        return f'{floor_id}-v1'

    def add_waypoint(self, request):
        name = str(request.get('display_name', '')).strip()
        if not name or len(name) > 64:
            raise ValueError('航点名称不能为空且不能超过 64 个字符')
        try:
            x, y, yaw = (float(request[key]) for key in ('x', 'y', 'yaw'))
        except (KeyError, TypeError, ValueError):
            raise ValueError('航点坐标或角度无效')
        if not all(math.isfinite(value) for value in (x, y, yaw)):
            raise ValueError('航点坐标或角度无效')
        path = self.poi_file(create=True)
        with self.poi_lock:
            try:
                document = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
            except FileNotFoundError:
                document = {}
            except (OSError, yaml.YAMLError) as exc:
                raise ValueError(f'无法读取航点文件: {exc}')
            if not isinstance(document, dict):
                document = {}
            pois = document.setdefault('pois', [])
            # 新 ID 取最大 wp_NNN 后一位（如已有 wp_005/wp_006 -> wp_007），
            # 不用“最小空闲号”，避免与现场 wp_001~wp_006 约定冲突。
            numbers = []
            for item in pois:
                if not isinstance(item, dict):
                    continue
                raw = str(item.get('id') or '')
                if raw.startswith('wp_') and raw[3:].isdigit():
                    numbers.append(int(raw[3:]))
            number = (max(numbers) + 1) if numbers else 1
            waypoint_id = f'wp_{number:03d}'
            pois.append({
                'id': waypoint_id, 'display_name': name, 'poi_type': 'waypoint',
                'floor_id': self.current_floor_id, 'area_id': f'{self.current_floor_id}_unassigned',
                'x': x, 'y': y, 'yaw': yaw, 'final_approach_profile': 'none',
                'enabled': True, 'map_version': self.floor_map_version(self.current_floor_id),
            })
            temporary = path.with_suffix(path.suffix + '.tmp')
            temporary.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding='utf-8')
            os.replace(temporary, path)
            self.poi_cache_key = None
        return waypoint_id

    def send_nav(self, poi_id):
        """发送航点：校验存在于当前楼层后发布 /hotel/goal_destination。"""
        poi_id = str(poi_id or '').strip()
        waypoints = self.load_waypoints()
        match = next((w for w in waypoints if w['id'] == poi_id), None)
        if match is None:
            raise ValueError(f'当前楼层 {self.current_floor_id} 没有航点 {poi_id!r}')
        msg = String()
        msg.data = poi_id
        self._goal_pub.publish(msg)
        return {
            'ok': True, 'id': poi_id, 'display_name': match['display_name'],
            'floor_id': self.current_floor_id,
            'note': '已发布 /hotel/goal_destination，小车将前往该航点',
        }

    def publish_navigation_mode(self):
        self._motion_mode_pub.publish(String(data=self.navigation_mode))

    def set_navigation_mode(self, mode):
        mode = str(mode or '').strip().lower()
        if mode not in ('omni', 'forward_facing'):
            raise ValueError(f'不支持的导航模式: {mode!r}')
        self.navigation_mode = mode
        self.navigation_mode_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.navigation_mode_file.with_suffix('.tmp')
        temporary.write_text(mode + '\n', encoding='utf-8')
        os.replace(temporary, self.navigation_mode_file)
        self.publish_navigation_mode()
        return {'ok': True, 'mode': mode}

    def on_llm_status(self, msg):
        text = str(msg.data or '')
        low = text.lower()
        if any(k in low for k in ('error', 'failed', 'unknown', 'not ready')):
            cls = 'bad'
        elif any(k in low for k in ('corrected', 'clarify', 'cancel', 'unsupported')):
            cls = 'warn'
        else:
            cls = 'ok'
        entry = {'t': time.strftime('%H:%M:%S'), 'msg': text, 'cls': cls}
        with self.lock:
            self.llm_log.append(entry)
            if len(self.llm_log) > self.llm_log_max:
                del self.llm_log[:len(self.llm_log) - self.llm_log_max]

    def send_llm(self, text):
        text = str(text or '').strip()
        if not text:
            raise ValueError('指令不能为空')
        if len(text) > 200:
            raise ValueError('指令过长')
        msg = String()
        msg.data = text
        self._llm_cmd_pub.publish(msg)
        entry = {'t': time.strftime('%H:%M:%S'), 'msg': f'➤ {text}', 'cls': 'me'}
        with self.lock:
            self.llm_log.append(entry)
            if len(self.llm_log) > self.llm_log_max:
                del self.llm_log[:len(self.llm_log) - self.llm_log_max]
        return {'ok': True, 'text': text, 'note': '已发布 /llm_command'}

    def snapshot(self):
        now = time.monotonic()
        with self.lock:
            age = {k: round(now-v, 2) if v else -1.0 for k, v in self.last.items()}
            snapshot = {'map': dict(self.map_info), 'pose': dict(self.pose) if self.pose else None,
                        'scan': list(self.scan),
                        'path': list(self.path), 'age': age,
                        'llm_log': list(self.llm_log)}
        snapshot['floor_id'] = self.current_floor_id
        snapshot['selected_map'] = self.selected_map
        snapshot['map_mode'] = self.map_mode
        snapshot['maps'] = self.available_maps
        snapshot['waypoints'] = self.load_waypoints()
        snapshot['navigation_mode'] = self.navigation_mode
        snapshot['diagnostics'] = self.diagnostics.snapshot()
        snapshot['follow_status'] = self.follow_status
        snapshot['mission_goal_status'] = self.mission_goal_status
        return snapshot


NODE = None


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        return

    def send_bytes(self, data, content_type, cache='no-store'):
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', cache)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        path = self.path.split('?', 1)[0]
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length > 65536:
                self.send_json({'error': '请求过大'}, 413)
                return
            raw = self.rfile.read(length) if length else b'{}'
            payload = json.loads(raw.decode('utf-8')) if raw else {}
            if path in ('/api/follow/start', '/api/follow/stop'):
                client = NODE.follow_clients[path.rsplit('/',1)[-1]]
                if not client.service_is_ready():
                    self.send_json({'error':'跟随服务未就绪'},503)
                else:
                    client.call_async(EmptyService.Request())
                    self.send_json({'submitted':True},202)
            elif path == '/api/waypoints':
                waypoint_id = NODE.add_waypoint(payload)
                self.send_json({'ok': True, 'id': waypoint_id}, 201)
            elif path == '/api/map/select':
                result = NODE.select_map(payload.get('map_id'))
                self.send_json(result)
            elif path == '/api/nav':
                result = NODE.send_nav(payload.get('id'))
                self.send_json(result)
            elif path == '/api/nav/mode':
                result = NODE.set_navigation_mode(payload.get('mode'))
                self.send_json(result)
            elif path == '/api/llm':
                result = NODE.send_llm(payload.get('text'))
                self.send_json(result)
            elif path == '/api/shutdown':
                self.send_json({'ok': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self.send_json({'error': 'not found'}, 404)
        except (ValueError, UnicodeDecodeError) as exc:
            self.send_json({'error': str(exc)}, 400)
        except Exception as exc:
            self.send_json({'error': f'服务器错误: {exc}'}, 500)

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/':
            self.send_bytes(HTML.encode(), 'text/html; charset=utf-8')
        elif path == '/api/incidents':
            files = sorted(NODE.diagnostics.directory.glob('incident-*.json'), reverse=True)[:100]
            links = ''.join(f'<li><a href="/api/incidents/{p.name}">{p.name}</a></li>' for p in files if re.fullmatch(r'incident-[0-9]+\.json', p.name))
            self.send_bytes(('<meta charset="utf-8"><h2>导航故障现场记录</h2><p>点击查看原始 JSON 数据。最多保留100份。</p><ul>'+links+'</ul>').encode(), 'text/html; charset=utf-8')
        elif path.startswith('/api/incidents/'):
            name = path.rsplit('/', 1)[-1]
            if not re.fullmatch(r'incident-[0-9]+\.json', name):
                self.send_error(400)
                return
            record = NODE.diagnostics.directory / name
            if record.is_file():
                self.send_bytes(record.read_bytes(), 'application/json; charset=utf-8')
            else:
                self.send_error(404)
        elif path == '/api/maps':
            self.send_json({'maps': NODE.available_maps, 'selected_map': NODE.selected_map})
        elif path == '/map.png':
            with NODE.lock:
                data = NODE.map_png
            if data:
                self.send_bytes(data, 'image/png', 'public, max-age=31536000, immutable')
            else:
                self.send_error(404)
        elif path == '/camera.jpg':
            candidates = ('/tmp/ddsm_semantic_detection.jpg', '/tmp/ddsm_semantic_live.jpg')
            file_path = next((p for p in candidates if os.path.exists(p)), None)
            if file_path:
                with open(file_path, 'rb') as f:
                    self.send_bytes(f.read(), 'image/jpeg')
            else:
                self.send_error(404)
        elif path == '/events':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            try:
                while rclpy.ok():
                    payload = json.dumps(NODE.snapshot(), separators=(',', ':')).encode()
                    self.wfile.write(b'data:' + payload + b'\n\n')
                    self.wfile.flush()
                    time.sleep(0.4)
            except (BrokenPipeError, ConnectionResetError):
                pass
        elif path == '/health':
            self.send_bytes(json.dumps(NODE.snapshot()).encode(), 'application/json')
        else:
            self.send_error(404)


def main():
    global NODE
    port = int(os.environ.get('LIGHT_DASHBOARD_PORT', '8503'))
    rclpy.init()
    NODE = DashboardNode()
    executor = SingleThreadedExecutor()
    executor.add_node(NODE)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()
    server = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    server.daemon_threads = True

    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print(f'Lightweight robot dashboard: http://0.0.0.0:{port}', flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        executor.shutdown()
        NODE.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
