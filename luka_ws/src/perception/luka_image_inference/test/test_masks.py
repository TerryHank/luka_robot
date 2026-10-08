import unittest
import numpy as np
from luka_image_inference.masks import mask_canvas

class Masks(unittest.TestCase):
    def test_real_roi_not_box(self):
        result=mask_canvas((4,4),[{'bbox':[1,1,3,3],'person_mask':np.array([[1,0],[0,1]])}])
        self.assertEqual(np.count_nonzero(result),2)
        self.assertEqual(result[1,2],0)
        self.assertEqual(result[1,1],255)

    def test_empty_is_valid_no_person(self):
        self.assertEqual(np.count_nonzero(mask_canvas((4,4),[])),0)

    def test_invalid_geometry_is_rejected(self):
        with self.assertRaises(ValueError):mask_canvas((4,4),[{'bbox':[1,1,3,3],'person_mask':np.ones((4,4))}])

if __name__=='__main__':unittest.main()
