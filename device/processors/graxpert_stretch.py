from typing import Optional

import numpy as np
from skimage.exposure import exposure
from skimage.util import img_as_float32

from device.processors.image_processor import ImageProcessor
from imaging.stretch import stretch, StretchParameters, StretchParameter


class GraxpertStretch(ImageProcessor):
    def process(
        self, image: np.ndarray, stretch_parameter: StretchParameter = "15% Bg, 3 sigma"
    ) -> Optional[np.ndarray]:
        image_array = img_as_float32(image)
        if np.min(image_array) < 0 or np.max(image_array > 1):
            image_array = exposure.rescale_intensity(image_array, out_range=(0, 1))

        image_display = stretch(image_array, StretchParameters(stretch_parameter))
        image_display = image_display * 255

        return image_display
