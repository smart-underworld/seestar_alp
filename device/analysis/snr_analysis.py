from typing import Optional

import numpy as np

from device.analysis.image_analysis import ImageAnalysisSingle
from imaging.snr import calculate_snr_auto


class SNRAnalysis(ImageAnalysisSingle):
    def analyze(self, image: np.ndarray) -> Optional[float]:
        try:
            return calculate_snr_auto(image)
        except:
            return None
