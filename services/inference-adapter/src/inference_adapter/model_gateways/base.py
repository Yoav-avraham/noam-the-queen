from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class BaseGateway(ABC):
    @abstractmethod
    async def __call__(self, x: np.ndarray, session_id: str, **kwargs):
        pass
