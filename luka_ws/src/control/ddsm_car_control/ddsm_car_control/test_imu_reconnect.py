"""Fault injection without opening hardware or publishing ROS messages."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import time
tree=ast.parse(Path(__file__).with_name('wit_imu_node.py').read_text())
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='WitImuNode')
cls.bases=[]
cls.body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in
          ('_disconnect_serial','_connect_serial','_poll_once')]
serial=SimpleNamespace(Serial=Mock())
ns={'time':time,'serial':serial,'WitNormalParser':Mock}
exec(compile(ast.Module(body=[cls],type_ignores=[]),'test','exec'),ns)
n=ns['WitImuNode']()
n.port='/dev/serial/by-id/test'; n.baud=921600; n.protocol='normal'
n.configure_output=False; n.get_logger=Mock(return_value=Mock())
n.serial=Mock(); old=n.serial
n._read_normal_sample=Mock(side_effect=OSError('disconnected'))
n._poll_once()
assert n.serial is None and old.close.called
n._poll_once(); serial.Serial.assert_not_called()
n.next_reconnect_time=0; serial.Serial.side_effect=OSError('absent')
n._poll_once(); assert n.serial is None
n.next_reconnect_time=0; serial.Serial.side_effect=None
n._poll_once(); assert n.serial is serial.Serial.return_value
assert serial.Serial.call_args.kwargs['port']==n.port
n._read_normal_sample=Mock(return_value=None)
n.last_publish_time=time.monotonic()-6; n.last_warn_time=0
n._poll_once(); assert n.serial is None
print('PASS: disconnect, backoff, missing device, stable-path reconnect, no-data timeout')
