from abc import abstractmethod, ABC
from typing import Optional

import numpy as np


class ImageAnalysisSingle(ABC):
    @abstractmethod
    def analyze(self, image: np.ndarray) -> Optional[float]:
        pass
