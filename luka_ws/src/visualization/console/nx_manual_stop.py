import sys,time
sys.path.insert(0,'/home/sunrise/luka_ws/src/control/ddsm_car_control')
from ddsm_car_control.zdt_y42_protocol import ZDTY42SerialBus
bus=ZDTY42SerialBus('/dev/nx_base',protocol='free',firmware='x',timeout=.03,free_ack_writes=False)
bus._serial.write_timeout=.15
errors=[]
try:
    for _ in range(3):
        for i in (1,2,3,4):
            try: bus.stop_motor(i,sync=False)
            except Exception as e: errors.append(str(e))
        time.sleep(.03)
finally: bus.close()
if errors: raise RuntimeError(str(errors))
