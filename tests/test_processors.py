import numpy as np

from device.processors.graxpert_stretch import GraxpertStretch
from device.processors.image_processor import ImageProcessor
from device.processors.simple_stretch import SimpleStretch


class BaseProcessorProbe(ImageProcessor):
    def process(self, image):
        return ImageProcessor.process(self, image)


def test_simple_stretch_returns_rescaled_image():
    image = np.array([[0.0, 10.0], [20.0, 30.0]], dtype=np.float32)

    output = SimpleStretch().process(image)

    assert output.shape == image.shape
    assert np.min(output) >= 0.0
    assert np.max(output) <= 30.0


def test_graxpert_stretch_rescales_out_of_range_then_multiplies(monkeypatch):
    calls = {"rescaled": False, "stretch_param": None}

    def fake_rescale(image_array, out_range):
        calls["rescaled"] = True
        assert out_range == (0, 1)
        return np.clip(image_array, 0, 1)

    def fake_stretch(image_array, stretch_params):
        calls["stretch_param"] = stretch_params
        return image_array + 0.5

    monkeypatch.setattr(
        "device.processors.graxpert_stretch.exposure.rescale_intensity", fake_rescale
    )
    monkeypatch.setattr("device.processors.graxpert_stretch.stretch", fake_stretch)

    image = np.array([[-2.0, 0.5], [1.2, 3.0]], dtype=np.float32)
    output = GraxpertStretch().process(image, "10% Bg, 2 sigma")

    assert calls["rescaled"] is True
    assert calls["stretch_param"] is not None
    assert output.shape == image.shape
    assert np.all(output >= 127.5)


def test_graxpert_stretch_skips_rescale_when_range_valid(monkeypatch):
    called = {"rescale": 0}

    def fake_rescale(image_array, out_range):
        called["rescale"] += 1
        return image_array

    monkeypatch.setattr(
        "device.processors.graxpert_stretch.exposure.rescale_intensity", fake_rescale
    )
    monkeypatch.setattr(
        "device.processors.graxpert_stretch.stretch",
        lambda image_array, _params: image_array,
    )

    image = np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32)
    output = GraxpertStretch().process(image)

    assert called["rescale"] == 0
    assert np.allclose(output, image * 255)


def test_image_processor_base_rescale_and_stretch(monkeypatch):
    calls = {"rescale": 0, "stretch": 0}

    def fake_rescale(image_array, out_range):
        calls["rescale"] += 1
        assert out_range == (0, 1)
        return np.clip(image_array, 0, 1)

    def fake_stretch(image_array, _params):
        calls["stretch"] += 1
        return image_array

    monkeypatch.setattr(
        "device.processors.image_processor.exposure.rescale_intensity", fake_rescale
    )
    monkeypatch.setattr("device.processors.image_processor.stretch", fake_stretch)

    image = np.array([[-1.0, 0.2], [0.8, 1.4]], dtype=np.float32)
    output = BaseProcessorProbe().process(image)

    assert calls["rescale"] == 1
    assert calls["stretch"] == 1
    assert np.min(output) >= 0.0
    assert np.max(output) <= 255.0


def test_image_processor_base_skips_rescale_when_within_range(monkeypatch):
    calls = {"rescale": 0}

    def fake_rescale(image_array, out_range):
        calls["rescale"] += 1
        return image_array

    monkeypatch.setattr(
        "device.processors.image_processor.exposure.rescale_intensity", fake_rescale
    )
    monkeypatch.setattr(
        "device.processors.image_processor.stretch",
        lambda image_array, _params: image_array,
    )

    image = np.array([[0.01, 0.02], [0.9, 1.0]], dtype=np.float32)
    output = BaseProcessorProbe().process(image)

    assert calls["rescale"] == 0
    assert np.allclose(output, image * 255)
