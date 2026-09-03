from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rpi_mastery.people import PersonDetector, camera_people


@pytest.fixture
def cv(monkeypatch):
    frame = SimpleNamespace(shape=(480, 640, 3))
    hog = Mock()
    hog.detectMultiScale.return_value = ([], [0.0, 2.0])
    capture = Mock()
    capture.isOpened.return_value = True
    capture.read.return_value = (True, frame)
    module = SimpleNamespace(
        HOGDescriptor=Mock(return_value=hog),
        HOGDescriptor_getDefaultPeopleDetector=Mock(return_value="model"),
        VideoCapture=Mock(return_value=capture),
        CAP_V4L2=200,
        CAP_PROP_FRAME_WIDTH=3,
        CAP_PROP_FRAME_HEIGHT=4,
        resize=Mock(side_effect=lambda frame, size: SimpleNamespace(shape=(*size[::-1], 3))),
    )
    monkeypatch.setattr("rpi_mastery.people.importlib.import_module", lambda name: module)
    return module


def test_model_and_scores(cv):
    detector = PersonDetector()
    result = detector.detect(SimpleNamespace(shape=(1080, 1920, 3)))
    cv.resize.assert_called_once()
    detector.hog.setSVMDetector.assert_called_once_with("model")
    assert [item.label for item in result] == ["person", "person"]
    assert result[0].confidence == 0.5
    assert 0.88 < result[1].confidence < 0.89


@pytest.mark.parametrize(
    "shape", [None, (480, 640), (480, 640, 4), (10, 64, 3), (128, 20, 3), (128, 8000, 3)]
)
def test_invalid_frame(cv, shape):
    with pytest.raises(ValueError):
        PersonDetector().detect(None if shape is None else SimpleNamespace(shape=shape))


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_score(cv, score):
    cv.HOGDescriptor().detectMultiScale.return_value = ([], [score])
    with pytest.raises(ValueError, match="non-finite"):
        PersonDetector().detect(SimpleNamespace(shape=(480, 640, 3)))


def test_missing_dependency(monkeypatch):
    def missing(name):
        raise ImportError(name)

    monkeypatch.setattr("rpi_mastery.people.importlib.import_module", missing)
    with pytest.raises(RuntimeError, match="optional vision"):
        PersonDetector()


@pytest.mark.parametrize(
    "device,frames",
    [
        ("https://camera", 1),
        ("/dev/video0/x", 1),
        (None, 1),
        ("/dev/video0", 0),
        ("/dev/video0", 301),
        ("/dev/video0", True),
        ("/dev/video0", 1.5),
    ],
)
def test_capture_validation(cv, device, frames):
    with pytest.raises(ValueError):
        list(camera_people(device, frames))
    cv.VideoCapture.assert_not_called()


def test_bounded_capture_releases(cv):
    assert len(list(camera_people("/dev/video0", 2))) == 2
    cv.VideoCapture.assert_called_once_with("/dev/video0", cv.CAP_V4L2)
    assert cv.VideoCapture().read.call_count == 2
    cv.VideoCapture().release.assert_called_once()


@pytest.mark.parametrize("failure", ["open", "read", "detect"])
def test_capture_failure_releases(cv, failure):
    if failure == "open":
        cv.VideoCapture().isOpened.return_value = False
    elif failure == "read":
        cv.VideoCapture().read.return_value = (False, None)
    else:
        cv.HOGDescriptor().detectMultiScale.side_effect = RuntimeError("model failure")
    with pytest.raises(RuntimeError):
        list(camera_people("/dev/video0", 1))
    cv.VideoCapture().release.assert_called_once()


def test_early_close_releases(cv):
    stream = camera_people("/dev/video0", 300)
    next(stream)
    stream.close()
    assert cv.VideoCapture().read.call_count == 1
    cv.VideoCapture().release.assert_called_once()
