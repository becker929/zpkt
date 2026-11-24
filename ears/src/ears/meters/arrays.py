"""Array type names shared by the instruments: audio is float64, shaped (samples, channels) unless said otherwise."""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]
Json = dict[str, Any]  # a JSON object as the instruments read and write it
ComplexArray = npt.NDArray[np.complex128]
