import ast
from pathlib import Path
tree=ast.parse(Path('/home/sunrise/luka_ws/system/runtime/tools/person_follow_node.py').read_text())
fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='safe_command')
scope={}
exec(compile(ast.Module(body=[fn],type_ignores=[]),'<test>','exec'),scope)
command=scope['safe_command']
scans={'upper':(10,2),'lower':(10,2)}
box=(0.4,0.2,0.2,0.3)
cmd,_=command(box,None,scans,10.1)
assert 0<cmd[0]<=0.12 and cmd[1]==0
assert command(box,None,scans,11)[0] is None
assert command(box,None,{'upper':(10,2)},10.1)[0] is None
assert command(box,None,{'upper':(10,2),'lower':(10,0.4)},10.1)[0] is None
assert command(None,box,scans,10.1)[0] is None
assert command((0.8,0.2,0.2,0.3),box,scans,10.1)[0] is None
assert command((0.4,0.0,0.2,0.8),None,scans,10.1)[0][0]==0
print('PASS: speed cap, no reverse, target loss/change, stale/missing/blocked lidar all verified without motion')
