import pytest

from rpi_mastery.hardware import SimulatedDigitalOutput


def test_simulated_output_tracks_values_and_closes_safely():
    output = SimulatedDigitalOutput()
    output.set(0.25)
    output.set(1.0)
    output.close()

    assert output.history == [0.25, 1.0]
    assert output.value == 0.0
    assert output.closed


def test_simulated_output_rejects_unsafe_range():
    output = SimulatedDigitalOutput()
    with pytest.raises(ValueError):
        output.set(1.1)
