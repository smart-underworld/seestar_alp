from abc import ABC, abstractmethod
from typing import Optional

import numpy as np
from skimage.exposure import exposure
from skimage.util import img_as_float32

from imaging.stretch import stretch, StretchParameters


class ImageProcessor(ABC):
    @abstractmethod
    def process(self, image: np.ndarray) -> Optional[np.ndarray]:
        image_array = img_as_float32(image)

        if np.min(image_array) < 0 or np.max(image_array > 1):
            image_array = exposure.rescale_intensity(image_array, out_range=(0, 1))

        image_display = stretch(image_array, StretchParameters("15% Bg, 3 sigma"))
        image_display = image_display * 255

        return image_display
