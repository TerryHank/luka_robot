"""YOLO26 person segmentation facade for the RDK S100.

Legacy callers keep importing Yolo26PersonSegmenter while runtime selection is
moved behind an explicit backend factory.
"""
from yolo26_bpu_person import MODEL, HBM
from runtime.factory import create_yolo26_person_segmenter


class Yolo26PersonSegmenter:
    def __new__(cls, confidence=.35, max_people=8):
        return create_yolo26_person_segmenter(
            confidence=confidence, max_people=max_people
        )
