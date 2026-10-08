import ast
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from .source_checks import ROOT,tree


class ExternalShutdownException(Exception):
    pass


@pytest.mark.parametrize('package,filename',[
    ('luka_base_gate','gate.py'),('luka_motion_gateway','node.py')])
@pytest.mark.parametrize('error,context_ok',[
    (RuntimeError('context not valid'),False),
    (ExternalShutdownException(),False),
    (KeyboardInterrupt(),True),
    (RuntimeError('unexpected callback failure'),True)])
def test_main_cleans_up_on_shutdown_without_hiding_active_context_errors(package,filename,error,context_ok):
    # Execute the real entrypoint with no ROS imports or serial constructor.
    path=ROOT/'control'/package/package/filename
    main=next(node for node in tree(path).body if isinstance(node,ast.FunctionDef) and node.name=='main')
    node=Mock()
    executor=Mock()
    executor.spin.side_effect=error
    ros=Mock()
    ros.ok.return_value=context_ok
    ros.spin.side_effect=error
    scope=dict(rclpy=ros,BaseGate=lambda:node,MotionGateway=lambda:node,
               MultiThreadedExecutor=lambda **_:executor,
               ExternalShutdownException=ExternalShutdownException,
               os=SimpleNamespace(environ={}))
    exec(compile(ast.Module(body=[main],type_ignores=[]),str(path),'exec'),scope)
    if type(error) is RuntimeError and context_ok:
        with pytest.raises(RuntimeError,match='unexpected callback failure'):scope['main']()
    else:
        scope['main']()
    node.destroy_node.assert_called_once()
    ros.try_shutdown.assert_called_once()
    if package=='luka_base_gate':
        node.checkpoint.assert_called_once()
        executor.shutdown.assert_called_once()
    elif context_ok:
        node.stop.assert_called_once()
    else:
        node.stop.assert_not_called()
        node.arbiter.stop.assert_called_once()
