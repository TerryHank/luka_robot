import numpy as np


def mask_canvas(shape, detections):
    """Keep the model's pixel masks; do not replace segmentation with rectangles."""
    height, width = shape
    output = np.zeros((height, width), dtype=np.uint8)
    for row in detections:
        x1, y1, x2, y2 = row['bbox']
        mask = np.asarray(row['person_mask'])
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise ValueError('mask bbox is outside the original RGB image')
        if mask.shape != (y2-y1, x2-x1):
            raise ValueError('mask shape does not match its ROI')
        output[y1:y2,x1:x2][mask != 0] = 255
    return output
