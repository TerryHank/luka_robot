import tempfile,unittest,numpy as np
from unittest.mock import patch
from nx_voiceprint import VoiceprintStore,VoiceprintWorker,identify

class VoiceprintTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.s=VoiceprintStore(self.tmp.name)
    def test_three_samples_and_private_status(self):
        p=self.s.begin('测试用户',1)
        for n in range(3):self.assertEqual(self.s.add(p['id'],[1,0,0]),(n+1,n==2))
        self.assertIsNone(self.s.pending());self.assertTrue(self.s.status()['profiles'][0]['ready'])
        self.assertNotIn('vector',str(self.s.status()))
        self.assertEqual(identify([1,0,0],self.s.profiles())['name'],'测试用户')
    def test_cancel_inflight_and_owner(self):
        p=self.s.begin('甲',1);self.s.delete(p['id'],2);self.assertIsNotNone(self.s.pending())
        self.s.delete(p['id'],1)
        with self.assertRaises(ValueError):self.s.add(p['id'],[1,0])
    def test_expiry(self):
        p=self.s.begin('甲',1)
        with patch('nx_voiceprint.time.time',return_value=1e12):
            self.assertIsNone(self.s.pending())
            with self.assertRaises(ValueError):self.s.add(p['id'],[1,0])
    def test_consistency_and_ambiguity(self):
        p=self.s.begin('甲',1);self.s.add(p['id'],[1,0])
        with self.assertRaises(ValueError):self.s.add(p['id'],[0,1])
        profiles=[{'id':'1','name':'甲','vector':[1,0]},{'id':'2','name':'乙','vector':[1,.01]}]
        self.assertEqual(identify([1,0],profiles)['state'],'unknown')
        self.assertEqual(identify([-1,0],profiles)['state'],'unknown')
    def test_bad_audio_before_model(self):
        w=VoiceprintWorker.__new__(VoiceprintWorker);w.extractor=None
        for a in [np.zeros(5000),np.zeros(48000),np.ones(48000),np.full(48000,np.nan)]:
            with self.assertRaises(ValueError):w.embedding(a,16000)

if __name__=='__main__':unittest.main()
