"""Exercise real-camera CLI wiring without opening hardware in CI."""

import json
import runpy
import sys
from pathlib import Path

import pytest

from rpi_mastery.vision import Detection

SCRIPT = Path(__file__).resolve().parents[1] / "projects/04_edge_vision_sentinel/main.py"


def test_camera_cli_emits_events_and_summary(monkeypatch, capsys):
    closed = []
    pauses = []

    def stream(device, frames):
        assert device == "/dev/video0"
        assert frames == 2
        try:
            yield [Detection("person", 0.9)]
            yield [Detection("person", 0.9)]
        finally:
            closed.append(True)

    monkeypatch.setattr("rpi_mastery.people.camera_people", stream)
    monkeypatch.setattr("time.sleep", pauses.append)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--camera", "/dev/video0", "--frames", "2"])
    runpy.run_path(str(SCRIPT), run_name="__main__")
    event, summary = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert event["label"] == "person"
    assert event["mode"] == "camera-hog"
    assert event["score_kind"] == "sigmoid_svm_margin_not_probability"
    assert summary["frames_processed"] == 2
    assert summary["events_emitted"] == 1
    assert summary["frames_saved"] == summary["frames_uploaded"] == 0
    assert pauses == [0.5]
    assert closed == [True]


def test_interrupt_closes_camera_generator(monkeypatch):
    closed = []

    def stream(device, frames):
        try:
            yield []
            yield []
        finally:
            closed.append(True)

    def interrupt(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr("rpi_mastery.people.camera_people", stream)
    monkeypatch.setattr("time.sleep", interrupt)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--camera", "/dev/video0", "--frames", "2"])
    with pytest.raises(KeyboardInterrupt):
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert closed == [True]


@pytest.mark.parametrize("interval", ["nan", "inf", "-1"])
def test_invalid_interval_never_opens_camera(monkeypatch, interval):
    def unexpected(*args):
        pytest.fail("camera must not be opened for invalid arguments")

    monkeypatch.setattr("rpi_mastery.people.camera_people", unexpected)
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), "--camera", "/dev/video0", "--interval", interval]
    )
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert error.value.code == 2
