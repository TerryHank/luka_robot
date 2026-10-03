"""Fixed-list service startup; web clients cannot choose commands or units."""
import subprocess,threading,time

SERVICES=[('nx-sensors','雷达与 IMU'),('nx-localization','地图定位'),
 ('nx-manual-base','底盘'),('nx-gamepad','手柄'),('nx-navigation','导航'),
 ('nx-agent','语言代理'),('nx-voice','露卡语音'),('qwen-chat','聊天模型服务'),
 ('locateanything-preview','相机与物体记忆')]

class FunctionStart:
    def __init__(self):
        self.lock=threading.Lock()
        self.job={'running':False,'message':'点击一键启动可补齐未运行的服务','error':None}

    def status(self):
        with self.lock:result=dict(self.job)
        try:
            p=subprocess.run(['/usr/bin/systemctl','is-active',*[s+'.service' for s,_ in SERVICES]],capture_output=True,text=True,timeout=5)
            states=p.stdout.strip().splitlines()
            result['services']=[{'id':s,'name':name,'state':states[i] if i<len(states) else 'unknown'} for i,(s,name) in enumerate(SERVICES)]
            result['all_active']=all(x['state']=='active' for x in result['services'])
        except Exception as exc:result.update(services=[],all_active=False,error=str(exc))
        return result

    def start(self,restart=False):
        with self.lock:
            if self.job['running']:return {'accepted':True,'message':'正在启动，请稍候'}
            self.job={'running':True,'message':'正在重启功能服务，请等待…' if restart else '正在启动小车服务…','error':None}
        threading.Thread(target=self.run,args=(restart,),daemon=True).start()
        return {'accepted':True,'message':self.job['message']}

    def run(self,restart=False):
        try:
            helper='/usr/local/sbin/nx-restart-functions' if restart else '/usr/local/sbin/nx-start-functions'
            p=subprocess.run(['/usr/bin/sudo','-n',helper],capture_output=True,text=True,timeout=180)
            if p.returncode:raise RuntimeError((p.stderr or p.stdout or '启动失败')[-1200:])
            relocalize=''
            if restart and getattr(self,'relocalize',None):
                time.sleep(5)
                try:
                    self.relocalize()
                    relocalize=' 已自动检查定位；仅在需要时缓慢自转，定位稳定即停。'
                except Exception as exc:
                    relocalize=' 自动重定位尚未启动：'+str(exc)+'；请在监控页重试。'
            message=('功能重启已完成；旧导航不会续走。' if restart else '启动请求已完成；导航前请检查地图定位。')+relocalize+'语音服务首次加载约需 35 秒。'
            with self.lock:self.job.update(running=False,message=message,error=None)
        except Exception as exc:
            with self.lock:self.job.update(running=False,message='部分服务未能启动，请查看下方状态',error=str(exc))
