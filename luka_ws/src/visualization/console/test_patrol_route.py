import tempfile,unittest,threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from nx_patrol_route import PatrolRoute
from nx_patrol_mission import PatrolMission

class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.rows=[dict(id=i,display_name=i,x=float(n),y=0,yaw=0) for n,i in enumerate(('wp_008','wp_009','wp_010','customer_desk'))]
        self.route=PatrolRoute(Path(self.temp.name)/'route.json',lambda:self.rows,lambda:'floor_4')
    def test_order_and_persistence(self):
        d=self.route.save({'revision':0,'ids':['customer_desk','wp_008','customer_desk'],'dwell_s':0})
        self.assertEqual([p['id'] for p in d['points']],d['ids'])
        self.assertEqual(self.route.document()['revision'],1)
    def test_conflict(self):
        b={'revision':0,'ids':['wp_008'],'dwell_s':4};self.route.save(b)
        with self.assertRaises(ValueError):self.route.save(b)
    def test_invalid(self):
        for ids,wait in [([],4),(['deleted'],4),(['wp_008']*31,4),(['wp_008'],-1),(['wp_008'],float('nan')),(['wp_008'],True)]:
            with self.assertRaises(ValueError):self.route.save({'revision':0,'ids':ids,'dwell_s':wait})
        self.assertFalse(self.route.path.exists())
    def test_deleted_and_floor(self):
        d=self.route.document();self.rows.pop(0)
        with self.assertRaises(ValueError):self.route.resolve(d)
        d['floor_id']='floor_3'
        with self.assertRaises(ValueError):self.route.resolve(d)
    def mission(self):
        sent=[];node=SimpleNamespace(nx_nav_outcome=4)
        m=PatrolMission(node,sent.append,lambda:None,lambda text:None,Path(self.temp.name)/'state.json')
        m.route_store=self.route;m.cancel=SimpleNamespace(wait=lambda _:False,is_set=lambda:False)
        return m,sent
    def test_execution_order(self):
        self.route.save({'revision':0,'ids':['customer_desk','wp_010','wp_008'],'dwell_s':0})
        d=self.route.document();m,sent=self.mission()
        def vision(path,body=None):
            return {'ok':True,'session_id':body['session_id']} if path=='/semantic/start' else {'ok':True,'running':False}
        with patch('nx_patrol_mission.vision',vision),patch('nx_patrol_mission.current_scope',return_value={'map_id':'test-map'}),patch.object(m,'memory_health',return_value=True):m.run_patrol(d,self.route.resolve(d))
        self.assertEqual(sent,d['ids']);self.assertEqual(m.state['mode'],'complete')
    def test_changed_waypoint_aborts(self):
        d=self.route.document();points=self.route.resolve(d);m,sent=self.mission();self.rows[0]['x']=90.
        with patch('nx_patrol_mission.vision',lambda path,body=None:{'ok':True,'session_id':body['session_id'],'running':False}),patch('nx_patrol_mission.current_scope',return_value={'map_id':'test-map'}),patch.object(m,'memory_health',return_value=True):m.run_patrol(d,points)
        self.assertFalse(sent);self.assertEqual(m.state['mode'],'failed')
    def test_active_route_edit_rejected(self):
        m,_=self.mission();m.active=lambda:True
        with self.assertRaises(ValueError):m.save_route({'revision':0,'ids':['wp_008']})

if __name__=='__main__':unittest.main()
