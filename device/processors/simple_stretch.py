from typing import Optional

import numpy as np
from skimage.exposure import exposure

from device.processors.image_processor import ImageProcessor


class SimpleStretch(ImageProcessor):
    def process(self, image: np.ndarray) -> Optional[np.ndarray]:
        # https://scikit-image.org/docs/stable/auto_examples/color_exposure/plot_equalize.html
        # Contrast stretching
        p2, p98 = np.percentile(image, (2, 99.5))
        # p2, p98 = np.percentile(img, (2, 98))
        img_rescale = exposure.rescale_intensity(image, in_range=(p2, p98))

        # Equalization
        # img_eq = exposure.equalize_hist(img)

        # Adaptive Equalization
        # img_adapteq = exposure.equalize_adapthist(img, clip_limit=0.03)

        # stretched_image = Stretch().stretch(img)
        # return stretched_image

        return img_rescale

