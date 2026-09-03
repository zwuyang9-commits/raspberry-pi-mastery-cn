"""Offline HOG person detection. Frames and bounding boxes never leave this module."""

from __future__ import annotations

import importlib
import math
import re

from .vision import Detection


class PersonDetector:
    """OpenCV's bundled pedestrian model; normalized margins are not probabilities."""

    def __init__(self):
        try:
            self.cv = importlib.import_module("cv2")
        except ImportError as error:
            raise RuntimeError(
                "install the optional vision dependencies: pip install '.[vision]'"
            ) from error
        self.hog = self.cv.HOGDescriptor()
        self.hog.setSVMDetector(self.cv.HOGDescriptor_getDefaultPeopleDetector())

    def detect(self, frame) -> list[Detection]:
        if frame is None or len(frame.shape) != 3 or frame.shape[2] != 3:
            raise ValueError("expected a nonempty BGR camera frame")
        height, width = frame.shape[:2]
        if height < 128 or width < 64:
            raise ValueError("camera frame is too small for the pedestrian detector")
        ratio = min(1.0, 640 / max(height, width))
        if ratio < 1:
            frame = self.cv.resize(frame, (int(width * ratio), int(height * ratio)))
        if frame.shape[0] < 128 or frame.shape[1] < 64:
            raise ValueError("camera aspect ratio is unsupported")
        _, weights = self.hog.detectMultiScale(frame, winStride=(8, 8), padding=(8, 8), scale=1.05)
        detections = []
        for weight in weights:
            score = float(weight)
            if not math.isfinite(score):
                raise ValueError("person detector returned a non-finite score")
            # Map SVM margin to [0,1] for the existing temporal filter, not accuracy.
            normalized = 1 / (1 + math.exp(-max(-60.0, min(60.0, score))))
            detections.append(Detection("person", normalized))
        return detections


def camera_people(device: str, frames: int):
    """Yield metadata for a bounded local capture, releasing the device on close.

    V4L2 drivers can block within read(); use an external process timeout for a
    hard wall-clock deadline. No URLs, network cameras, preview or file recording.
    """
    if not isinstance(device, str) or not re.fullmatch(r"/dev/video[0-9]+", device):
        raise ValueError("camera must be a local /dev/videoN device")
    if type(frames) is not int or not 1 <= frames <= 300:
        raise ValueError("live capture frames must be an integer between 1 and 300")
    detector = PersonDetector()
    cv = detector.cv
    capture = cv.VideoCapture(device, cv.CAP_V4L2)
    try:
        if not capture.isOpened():
            raise RuntimeError("cannot open camera; check device, permissions and other users")
        capture.set(cv.CAP_PROP_FRAME_WIDTH, 640)
        capture.set(cv.CAP_PROP_FRAME_HEIGHT, 480)
        for _ in range(frames):
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError("camera frame read failed")
            detections = detector.detect(frame)
            del frame
            yield detections
    finally:
        capture.release()
