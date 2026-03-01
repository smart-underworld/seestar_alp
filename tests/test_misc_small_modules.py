import numpy as np
import pytest

from device.abstract_imager import AbstractImager
from device.actions import goto_sun
from device.analysis.snr_analysis import SNRAnalysis


def test_goto_sun_noop_returns_none():
    assert goto_sun(object()) is None


def test_abstract_imager_cannot_instantiate():
    with pytest.raises(TypeError):
        AbstractImager()


def test_abstract_imager_concrete_subclass():
    class ConcreteImager(AbstractImager):
        def get_frame(self):
            return b"frame"

        def get_live_status(self):
            return {"ok": True}

    imager = ConcreteImager()
    assert imager.get_frame() == b"frame"
    assert imager.get_live_status() == {"ok": True}


def test_snr_analysis_success_path(monkeypatch):
    monkeypatch.setattr(
        "device.analysis.snr_analysis.calculate_snr_auto", lambda image: 12.34
    )
    snr = SNRAnalysis().analyze(np.zeros((4, 4)))
    assert snr == 12.34


def test_snr_analysis_exception_returns_none(monkeypatch):
    def raises(_image):
        raise RuntimeError("bad image")

    monkeypatch.setattr("device.analysis.snr_analysis.calculate_snr_auto", raises)
    snr = SNRAnalysis().analyze(np.zeros((4, 4)))
    assert snr is None
