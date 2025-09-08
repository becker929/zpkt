from typing import Dict, Tuple, List, Optional, Any
from pathlib import Path
from dataclasses import dataclass
import numpy as np

@dataclass
class FeatureWeights:
    """Weighted feature set for multi-feature fitness calculation."""
    # Spectral features
    spectral_centroid: float = 0.0
    spectral_bandwidth: float = 0.0
    spectral_rolloff: float = 0.0
    spectral_contrast: float = 0.0
    spectral_flatness: float = 0.0

    # Temporal features
    zero_crossing_rate: float = 0.0
    rms_energy: float = 0.0

    # Harmonic features
    chroma_mean: float = 0.0
    tonnetz_mean: float = 0.0

    # Cepstral features
    mfcc_mean: float = 0.0

    # Rhythm features
    tempo: float = 0.0

    def get_active_features(self) -> Dict[str, float]:
        """Return only features with non-zero weights."""
        return {k: v for k, v in self.__dict__.items() if v != 0.0}

@dataclass
class ScalarFeatures:
    """Scalar feature values extracted from audio."""
    spectral_centroid: float = 0.0
    spectral_bandwidth: float = 0.0
    spectral_rolloff: float = 0.0
    spectral_contrast: float = 0.0
    spectral_flatness: float = 0.0
    zero_crossing_rate: float = 0.0
    rms_energy: float = 0.0
    chroma_mean: float = 0.0
    tonnetz_mean: float = 0.0
    mfcc_mean: float = 0.0
    tempo: float = 0.0

# Type aliases
SerumParameters = Dict[str, float]  # param_id -> value
ParameterConstraintSet = Dict[str, Tuple[float, float]]  # param_id -> (min, max)