"""Runtime adapters for the RDK S100 person segmentation pipeline."""
from .factory import create_yolo26_person_segmenter

__all__ = ["create_yolo26_person_segmenter"]
