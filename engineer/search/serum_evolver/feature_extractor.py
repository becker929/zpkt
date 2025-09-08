from abc import ABC, abstractmethod
from pathlib import Path
import numpy as np
import librosa
import soundfile as sf
from typing import Dict, Any
import logging

from .interfaces import FeatureWeights, ScalarFeatures

logger = logging.getLogger(__name__)


class IFeatureExtractor(ABC):
    """Interface for audio feature extraction."""

    @abstractmethod
    def extract_scalar_features(self, audio_path: Path,
                              feature_weights: FeatureWeights) -> ScalarFeatures:
        """Extract scalar features from audio file."""
        pass

    @abstractmethod
    def compute_feature_distance(self, target_features: ScalarFeatures,
                               actual_features: ScalarFeatures,
                               feature_weights: FeatureWeights) -> float:
        """Compute weighted distance between feature sets."""
        pass


class LibrosaFeatureExtractor(IFeatureExtractor):
    """Librosa-based feature extraction for audio analysis.
    
    Extracts scalar features from audio files using librosa library.
    Optimized for performance by only computing features with non-zero weights.
    """
    
    def __init__(self, sample_rate: int = 44100, hop_length: int = 512):
        """Initialize feature extractor.
        
        Args:
            sample_rate: Target sample rate for audio loading
            hop_length: Hop length for spectral analysis
        """
        self.sample_rate = sample_rate
        self.hop_length = hop_length
        
    def extract_scalar_features(self, audio_path: Path,
                              feature_weights: FeatureWeights) -> ScalarFeatures:
        """Extract scalar features from audio file.
        
        Only computes features with non-zero weights for efficiency.
        
        Args:
            audio_path: Path to audio file
            feature_weights: Weights for each feature type
            
        Returns:
            ScalarFeatures object containing extracted feature values
            
        Raises:
            FileNotFoundError: If audio file doesn't exist
            ValueError: If audio file can't be loaded or processed
        """
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
            
        try:
            # Load audio file at target sample rate, mono
            y, sr = librosa.load(str(audio_path), sr=self.sample_rate, mono=True)
            
            if len(y) == 0:
                raise ValueError(f"Audio file is empty or corrupted: {audio_path}")
                
            logger.debug(f"Loaded audio: {len(y)} samples at {sr}Hz")
            
        except Exception as e:
            raise ValueError(f"Failed to load audio file {audio_path}: {str(e)}")
        
        # Initialize result object
        features = ScalarFeatures()
        
        # Get only features with non-zero weights for efficiency
        active_features = feature_weights.get_active_features()
        
        if not active_features:
            logger.warning("No active features specified, returning zero features")
            return features
            
        # Cache commonly used spectral representation
        stft = None
        if any(feat.startswith('spectral_') for feat in active_features):
            stft = librosa.stft(y, hop_length=self.hop_length)
        
        try:
            # Spectral features
            if 'spectral_centroid' in active_features:
                centroid = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=self.hop_length)
                features.spectral_centroid = float(np.mean(centroid))
                
            if 'spectral_bandwidth' in active_features:
                bandwidth = librosa.feature.spectral_bandwidth(y=y, sr=sr, hop_length=self.hop_length)
                features.spectral_bandwidth = float(np.mean(bandwidth))
                
            if 'spectral_rolloff' in active_features:
                rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr, hop_length=self.hop_length)
                features.spectral_rolloff = float(np.mean(rolloff))
                
            if 'spectral_contrast' in active_features:
                contrast = librosa.feature.spectral_contrast(y=y, sr=sr, hop_length=self.hop_length)
                features.spectral_contrast = float(np.mean(contrast))
                
            if 'spectral_flatness' in active_features:
                flatness = librosa.feature.spectral_flatness(y=y, hop_length=self.hop_length)
                features.spectral_flatness = float(np.mean(flatness))
            
            # Temporal features
            if 'zero_crossing_rate' in active_features:
                zcr = librosa.feature.zero_crossing_rate(y, hop_length=self.hop_length)
                features.zero_crossing_rate = float(np.mean(zcr))
                
            if 'rms_energy' in active_features:
                rms = librosa.feature.rms(y=y, hop_length=self.hop_length)
                features.rms_energy = float(np.mean(rms))
            
            # Harmonic features
            if 'chroma_mean' in active_features:
                chroma = librosa.feature.chroma_stft(y=y, sr=sr, hop_length=self.hop_length)
                features.chroma_mean = float(np.mean(chroma))
                
            if 'tonnetz_mean' in active_features:
                tonnetz = librosa.feature.tonnetz(y=librosa.effects.harmonic(y), sr=sr)
                features.tonnetz_mean = float(np.mean(tonnetz))
            
            # Cepstral features
            if 'mfcc_mean' in active_features:
                mfccs = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=1, hop_length=self.hop_length)
                features.mfcc_mean = float(np.mean(mfccs[0]))  # First coefficient only
            
            # Rhythm features
            if 'tempo' in active_features:
                try:
                    tempo, _ = librosa.beat.beat_track(y=y, sr=sr, hop_length=self.hop_length)
                    # Handle scalar and array cases, and ensure valid tempo
                    if hasattr(tempo, '__len__'):
                        tempo_val = float(tempo[0]) if len(tempo) > 0 else 120.0
                    else:
                        tempo_val = float(tempo)
                    
                    # Use a reasonable default if tempo detection fails or returns invalid values
                    features.tempo = tempo_val if tempo_val > 0 else 120.0
                except:
                    # Fallback to default tempo if beat tracking fails
                    features.tempo = 120.0
                
        except Exception as e:
            logger.error(f"Error extracting features from {audio_path}: {str(e)}")
            raise ValueError(f"Feature extraction failed: {str(e)}")
        
        logger.debug(f"Extracted {len(active_features)} features from {audio_path}")
        return features
    
    def compute_feature_distance(self, target_features: ScalarFeatures,
                               actual_features: ScalarFeatures,
                               feature_weights: FeatureWeights) -> float:
        """Compute weighted Euclidean distance between feature sets.
        
        Only features with non-zero weights contribute to the distance calculation.
        
        Args:
            target_features: Target feature values
            actual_features: Actual feature values
            feature_weights: Weights for each feature
            
        Returns:
            Weighted Euclidean distance between feature sets
            
        Raises:
            ValueError: If feature sets are incompatible
        """
        active_weights = feature_weights.get_active_features()
        
        if not active_weights:
            logger.warning("No active features for distance calculation")
            return 0.0
        
        total_distance = 0.0
        total_weight = 0.0
        
        # Convert feature objects to dictionaries for easier iteration
        target_dict = target_features.__dict__
        actual_dict = actual_features.__dict__
        
        for feature_name, weight in active_weights.items():
            if feature_name not in target_dict or feature_name not in actual_dict:
                logger.warning(f"Feature {feature_name} not found in feature sets")
                continue
                
            target_val = target_dict[feature_name]
            actual_val = actual_dict[feature_name]
            
            # Compute squared difference weighted by feature importance
            diff = (target_val - actual_val) ** 2
            weighted_diff = weight * diff
            
            total_distance += weighted_diff
            total_weight += weight
        
        if total_weight == 0.0:
            return 0.0
        
        # Return weighted root mean square distance
        return np.sqrt(total_distance / total_weight)
    
    def _normalize_features(self, features: ScalarFeatures,
                          normalization_params: Dict[str, Dict[str, float]]) -> ScalarFeatures:
        """Normalize features using provided parameters.
        
        Args:
            features: Raw feature values
            normalization_params: Dict mapping feature names to {'mean': float, 'std': float}
            
        Returns:
            Normalized features
        """
        normalized = ScalarFeatures()
        
        for feature_name in features.__dict__:
            raw_value = getattr(features, feature_name)
            
            if feature_name in normalization_params:
                params = normalization_params[feature_name]
                mean = params['mean']
                std = params['std']
                
                if std > 0:
                    normalized_value = (raw_value - mean) / std
                else:
                    normalized_value = 0.0
                    
                setattr(normalized, feature_name, normalized_value)
            else:
                setattr(normalized, feature_name, raw_value)
        
        return normalized