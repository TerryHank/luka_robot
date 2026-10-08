import tempfile
from pathlib import Path
import sqlite3
import unittest
import numpy as np
from luka_visual_slam.contracts import session_database, masked_depth, validate_pair


class Contracts(unittest.TestCase):
    def test_uint16_depth_units_preserved(self):
        d=np.array([[1000,2000]],dtype=np.uint16)
        self.assertEqual(masked_depth(d,np.array([[0,255]],np.uint8)).tolist(),[[1000,0]])
        self.assertEqual(d.tolist(),[[1000,2000]])

    def test_float_depth_uses_nan(self):
        out=masked_depth(np.array([[1.,2.]],np.float32),np.array([[0,1]],np.uint8))
        self.assertEqual(out[0,0],1.);self.assertTrue(np.isnan(out[0,1]))

    def test_invalid_mask_rejected(self):
        for mask in (np.zeros((2,2),np.uint8),np.zeros((1,2),np.float32)):
            with self.assertRaises(ValueError):masked_depth(np.ones((1,2),np.uint16),mask)

    def test_sync_age_and_frame_contract(self):
        validate_pair([9.98,10.,10.,10.],['optical']*4,10.1)
        for stamps,frames,now in (([9.,10.],['a','a'],10.),([10.,10.],['a','b'],10.),([10.,10.],['a','a'],11.)):
            with self.assertRaises(ValueError):validate_pair(stamps,frames,now)

    def test_mapping_never_overwrites(self):
        with tempfile.TemporaryDirectory() as root:
            a=session_database('mapping','',root);b=session_database('mapping','',root)
            self.assertNotEqual(a,b)
            with self.assertRaises(ValueError):session_database('mapping',a,root)

    def test_localization_copies_database(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/'original.db'
            with sqlite3.connect(source) as c:c.execute('CREATE TABLE Node(id integer)');c.execute('INSERT INTO Node VALUES(7)')
            before=source.read_bytes();target=session_database('localization',str(source),root)
            with sqlite3.connect(target) as c:
                self.assertEqual(c.execute('SELECT id FROM Node').fetchone()[0],7)
                c.execute('DELETE FROM Node')
            self.assertEqual(source.read_bytes(),before)

    def test_localization_requires_map(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):session_database('localization',root+'/missing.db',root)


if __name__=='__main__':unittest.main()
