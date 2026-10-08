"""Fixed S100 service list for the existing one-click controls."""
import subprocess
import threading


SERVICES=(
    ('luka-ws-hardware@sensors.service','雷达与 IMU',True),
    ('luka-ws-hardware@manual_base.service','底盘',True),
    ('luka-ws-hardware@localization.service','地图定位',True),
    ('luka-ws-hardware@navigation.service','导航',True),
    ('luka-ws-hardware@voice.service','露卡语音',True),
    ('luka-ws-chat.service','聊天模型服务',True),
    ('luka-ws-agent.service','语言代理',True),
    ('luka-ws-vision.service','相机与物体记忆',True),
    ('luka-ws-people.service','人体识别',True),
    ('luka-ws-object-api.service','物体识别',True),
    ('luka-ws-dashboard.service','监控页面',True),
    ('luka-ws-hardware@gamepad.service','实体手柄（等待接收器）',False),
)


class FunctionStart:
    def __init__(self):
        self.lock=threading.Lock()
        self.job={'running':False,'message':'可检查或启动小车服务','error':None}
        self.relocalize=None

    def status(self):
        with self.lock:result=dict(self.job)
        try:
            units=[unit for unit,_,_ in SERVICES]
            proc=subprocess.run(['/usr/bin/systemctl','is-active',*units],
                                capture_output=True,text=True,timeout=8)
            states=proc.stdout.strip().splitlines()
            result['services']=[{'id':unit,'name':name,'state':states[i] if i<len(states) else 'unknown',
                                 'required':required}
                                for i,(unit,name,required) in enumerate(SERVICES)]
            result['all_active']=all(row['state']=='active' for row in result['services'] if row['required'])
        except Exception as exc:
            result.update(services=[],all_active=False,error=str(exc))
        return result

    def start(self,restart=False):
        with self.lock:
            if self.job['running']:return {'accepted':True,'message':'正在启动，请稍候'}
        if not restart and self.status()['all_active']:
            return {'accepted':True,'message':'小车功能已运行，无需重复启动'}
        with self.lock:
            self.job={'running':True,'message':'正在重启功能服务…' if restart else '正在启动小车服务…',
                      'error':None}
        threading.Thread(target=self.run,args=(restart,),daemon=True).start()
        return {'accepted':True,'message':self.job['message']}

    def run(self,restart=False):
        try:
            operation='restart' if restart else 'start'
            localization_started=False
            localization_check=''
            for unit,_,required in SERVICES:
                if not required or unit=='luka-ws-dashboard.service':continue
                proc=subprocess.run(['/usr/bin/sudo','-n','/usr/bin/systemctl',operation,unit],
                                    capture_output=True,text=True,timeout=35)
                if proc.returncode:
                    raise RuntimeError(unit+': '+(proc.stderr or proc.stdout or '启动失败')[-400:])
                if unit=='luka-ws-hardware@localization.service':
                    localization_started=True
                # Start the stationary check as soon as navigation is available.
                # Later camera/people failures must not skip localization.
                if unit=='luka-ws-hardware@navigation.service' and localization_started and self.relocalize:
                    try:
                        self.relocalize()
                        localization_check=' 已启动静态定位核验，请核对地图箭头。'
                    except Exception as exc:
                        localization_check=' 静态定位核验未启动：'+str(exc)+'。'
            message=('功能重启已完成；旧导航不会续走。' if restart else
                     '小车服务启动已完成。')+localization_check
            with self.lock:self.job.update(running=False,message=message,error=None)
        except Exception as exc:
            with self.lock:self.job.update(running=False,message='部分服务未能启动'+locals().get('localization_check',''),error=str(exc))
