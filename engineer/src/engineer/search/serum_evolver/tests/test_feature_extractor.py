"""
Tests for LibrosaFeatureExtractor class.

Tests include:
- Feature extraction with synthetic audio signals
- Weighted distance calculation
- Performance optimization with selective feature computation
- Audio loading error handling
- Edge cases and robustness
"""

import pytest
import numpy as np
import tempfile
from pathlib import Path
import soundfile as sf
from unittest.mock import Mock, patch

from serum_evolver.feature_extractor import LibrosaFeatureExtractor, IFeatureExtractor
from serum_evolver.interfaces import FeatureWeights, ScalarFeatures


class TestLibrosaFeatureExtractor:
    """Test suite for LibrosaFeatureExtractor."""

    @pytest.fixture
    def extractor(self):
        """Create feature extractor instance."""
        return LibrosaFeatureExtractor(sample_rate=44100, hop_length=512)

    @pytest.fixture
    def feature_weights_all_active(self):
        """Create feature weights with all features active."""
        return FeatureWeights(
            spectral_centroid=1.0,
            spectral_bandwidth=1.0,
            spectral_rolloff=1.0,
            spectral_contrast=1.0,
            spectral_flatness=1.0,
            zero_crossing_rate=1.0,
            rms_energy=1.0,
            chroma_mean=1.0,
            tonnetz_mean=1.0,
            mfcc_mean=1.0,
            tempo=1.0
        )

    @pytest.fixture
    def feature_weights_selective(self):
        """Create feature weights with only some features active."""
        return FeatureWeights(
            spectral_centroid=1.0,
            rms_energy=0.5,
            tempo=2.0,
            # All others remain 0.0 (inactive)
        )

    @pytest.fixture
    def feature_weights_inactive(self):
        """Create feature weights with no active features."""
        return FeatureWeights()  # All default to 0.0

    def create_test_audio_file(self, duration=1.0, sample_rate=44100, frequency=440.0):
        """Create a temporary audio file for testing.
        
        Args:
            duration: Duration in seconds
            sample_rate: Sample rate in Hz
            frequency: Sine wave frequency in Hz
            
        Returns:
            Path to temporary audio file
        """
        # Generate sine wave
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        audio = 0.3 * np.sin(2 * np.pi * frequency * t)
        
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        sf.write(temp_file.name, audio, sample_rate)
        temp_file.close()
        
        return Path(temp_file.name)

    def create_test_noise_file(self, duration=1.0, sample_rate=44100):
        """Create a temporary white noise audio file for testing."""
        audio = 0.1 * np.random.randn(int(sample_rate * duration))
        
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        sf.write(temp_file.name, audio, sample_rate)
        temp_file.close()
        
        return Path(temp_file.name)

    def test_interface_compliance(self, extractor):
        """Test that LibrosaFeatureExtractor implements IFeatureExtractor interface."""
        assert isinstance(extractor, IFeatureExtractor)
        assert hasattr(extractor, 'extract_scalar_features')
        assert hasattr(extractor, 'compute_feature_distance')

    def test_initialization(self):
        """Test feature extractor initialization with custom parameters."""
        extractor = LibrosaFeatureExtractor(sample_rate=22050, hop_length=1024)
        assert extractor.sample_rate == 22050
        assert extractor.hop_length == 1024

    def test_extract_features_sine_wave(self, extractor, feature_weights_all_active):
        """Test feature extraction from a pure sine wave."""
        audio_file = self.create_test_audio_file(duration=2.0, frequency=440.0)
        
        try:
            features = extractor.extract_scalar_features(audio_file, feature_weights_all_active)
            
            # Verify all features are extracted
            assert isinstance(features, ScalarFeatures)
            assert features.spectral_centroid > 0
            assert features.spectral_bandwidth >= 0
            assert features.spectral_rolloff > 0
            assert features.spectral_contrast >= 0
            assert features.spectral_flatness >= 0
            assert features.zero_crossing_rate >= 0
            assert features.rms_energy > 0
            assert features.chroma_mean >= 0
            assert features.tonnetz_mean != 0  # Should have harmonic content
            assert features.mfcc_mean != 0
            assert features.tempo >= 120.0  # Should be 120.0 (default) or detected tempo
            
            # Sine wave should have low zero crossing rate
            assert features.zero_crossing_rate < 0.1
            
            # Sine wave should have moderate RMS energy
            assert 0.1 < features.rms_energy < 0.5
            
        finally:
            audio_file.unlink()

    def test_extract_features_white_noise(self, extractor, feature_weights_all_active):
        """Test feature extraction from white noise."""
        audio_file = self.create_test_noise_file(duration=2.0)
        
        try:
            features = extractor.extract_scalar_features(audio_file, feature_weights_all_active)
            
            # White noise should have different characteristics than sine wave
            assert features.spectral_centroid > 0
            assert features.spectral_flatness > 0.5  # Flat spectrum
            assert features.zero_crossing_rate > 0.4  # High zero crossing
            assert features.rms_energy > 0
            
        finally:
            audio_file.unlink()

    def test_selective_feature_extraction(self, extractor, feature_weights_selective):
        """Test that only features with non-zero weights are computed."""
        audio_file = self.create_test_audio_file(duration=1.0, frequency=880.0)
        
        try:
            with patch.object(extractor, 'extract_scalar_features', wraps=extractor.extract_scalar_features) as mock_extract:
                features = extractor.extract_scalar_features(audio_file, feature_weights_selective)
                
                # Only active features should have non-zero values (or reasonable values)
                assert features.spectral_centroid > 0  # Active
                assert features.rms_energy > 0  # Active
                assert features.tempo >= 120.0  # Active (should be default 120.0 or detected)
                
                # Inactive features should remain at default (0.0)
                assert features.spectral_bandwidth == 0.0  # Inactive
                assert features.spectral_rolloff == 0.0  # Inactive
                assert features.spectral_contrast == 0.0  # Inactive
                assert features.spectral_flatness == 0.0  # Inactive
                assert features.zero_crossing_rate == 0.0  # Inactive
                assert features.chroma_mean == 0.0  # Inactive
                assert features.tonnetz_mean == 0.0  # Inactive
                assert features.mfcc_mean == 0.0  # Inactive
                
        finally:
            audio_file.unlink()

    def test_no_active_features(self, extractor, feature_weights_inactive):
        """Test behavior when no features are active."""
        audio_file = self.create_test_audio_file()
        
        try:
            features = extractor.extract_scalar_features(audio_file, feature_weights_inactive)
            
            # All features should be zero
            assert all(getattr(features, attr) == 0.0 for attr in features.__dict__)
            
        finally:
            audio_file.unlink()

    def test_file_not_found_error(self, extractor, feature_weights_all_active):
        """Test error handling for non-existent audio files."""
        non_existent_path = Path("non_existent_file.wav")
        
        with pytest.raises(FileNotFoundError, match="Audio file not found"):
            extractor.extract_scalar_features(non_existent_path, feature_weights_all_active)

    def test_empty_audio_file_error(self, extractor, feature_weights_all_active):
        """Test error handling for empty audio files."""
        # Create empty audio file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        sf.write(temp_file.name, np.array([]), 44100)
        temp_file.close()
        audio_file = Path(temp_file.name)
        
        try:
            with pytest.raises(ValueError, match="Audio file is empty or corrupted"):
                extractor.extract_scalar_features(audio_file, feature_weights_all_active)
        finally:
            audio_file.unlink()

    def test_invalid_audio_file_error(self, extractor, feature_weights_all_active):
        """Test error handling for invalid audio files."""
        # Create text file with .wav extension
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav', mode='w')
        temp_file.write("This is not an audio file")
        temp_file.close()
        audio_file = Path(temp_file.name)
        
        try:
            with pytest.raises(ValueError, match="Failed to load audio file"):
                extractor.extract_scalar_features(audio_file, feature_weights_all_active)
        finally:
            audio_file.unlink()

    def test_compute_feature_distance_basic(self, extractor):
        """Test basic weighted distance calculation."""
        target = ScalarFeatures(
            spectral_centroid=1000.0,
            rms_energy=0.5,
            tempo=120.0
        )
        
        actual = ScalarFeatures(
            spectral_centroid=1200.0,
            rms_energy=0.3,
            tempo=140.0
        )
        
        weights = FeatureWeights(
            spectral_centroid=1.0,
            rms_energy=2.0,
            tempo=0.5
        )
        
        distance = extractor.compute_feature_distance(target, actual, weights)
        
        # Manual calculation for verification
        # spectral_centroid: weight=1.0, diff=(1200-1000)^2=40000
        # rms_energy: weight=2.0, diff=(0.3-0.5)^2=0.04
        # tempo: weight=0.5, diff=(140-120)^2=400
        # total_distance = 1.0*40000 + 2.0*0.04 + 0.5*400 = 40000 + 0.08 + 200 = 40200.08
        # total_weight = 1.0 + 2.0 + 0.5 = 3.5
        # expected_distance = sqrt(40200.08 / 3.5) ≈ sqrt(11485.737) ≈ 107.17
        
        assert distance > 0
        assert abs(distance - 107.17) < 1.0  # Allow for small numerical differences

    def test_compute_feature_distance_identical_features(self, extractor):
        """Test distance calculation for identical features."""
        features = ScalarFeatures(
            spectral_centroid=1000.0,
            rms_energy=0.5,
            tempo=120.0
        )
        
        weights = FeatureWeights(
            spectral_centroid=1.0,
            rms_energy=1.0,
            tempo=1.0
        )
        
        distance = extractor.compute_feature_distance(features, features, weights)
        assert distance == 0.0

    def test_compute_feature_distance_no_active_features(self, extractor):
        """Test distance calculation with no active features."""
        target = ScalarFeatures(spectral_centroid=1000.0)
        actual = ScalarFeatures(spectral_centroid=1200.0)
        weights = FeatureWeights()  # All weights are 0.0
        
        distance = extractor.compute_feature_distance(target, actual, weights)
        assert distance == 0.0

    def test_compute_feature_distance_single_feature(self, extractor):
        """Test distance calculation with single active feature."""
        target = ScalarFeatures(spectral_centroid=1000.0)
        actual = ScalarFeatures(spectral_centroid=1300.0)
        weights = FeatureWeights(spectral_centroid=2.0)
        
        distance = extractor.compute_feature_distance(target, actual, weights)
        
        # Expected: sqrt(2.0 * (1300-1000)^2 / 2.0) = sqrt(90000) = 300.0
        assert abs(distance - 300.0) < 0.01

    def test_feature_extraction_consistency(self, extractor, feature_weights_all_active):
        """Test that feature extraction is consistent across multiple runs."""
        audio_file = self.create_test_audio_file(duration=1.0, frequency=440.0)
        
        try:
            # Extract features multiple times
            features1 = extractor.extract_scalar_features(audio_file, feature_weights_all_active)
            features2 = extractor.extract_scalar_features(audio_file, feature_weights_all_active)
            
            # Results should be identical
            for attr in features1.__dict__:
                assert abs(getattr(features1, attr) - getattr(features2, attr)) < 1e-6
                
        finally:
            audio_file.unlink()

    def test_different_sample_rates(self):
        """Test feature extraction with different sample rates."""
        # Test with different sample rate
        extractor_22k = LibrosaFeatureExtractor(sample_rate=22050)
        extractor_44k = LibrosaFeatureExtractor(sample_rate=44100)
        
        weights = FeatureWeights(spectral_centroid=1.0, rms_energy=1.0)
        
        # Create test file at 44.1kHz
        audio_file = self.create_test_audio_file(duration=1.0, sample_rate=44100, frequency=1000.0)
        
        try:
            features_22k = extractor_22k.extract_scalar_features(audio_file, weights)
            features_44k = extractor_44k.extract_scalar_features(audio_file, weights)
            
            # Features should be similar but not identical due to resampling
            assert abs(features_22k.spectral_centroid - features_44k.spectral_centroid) < 100
            assert abs(features_22k.rms_energy - features_44k.rms_energy) < 0.1
            
        finally:
            audio_file.unlink()

    def test_performance_selective_computation(self, extractor):
        """Test that selective feature computation improves performance."""
        audio_file = self.create_test_audio_file(duration=2.0)
        
        weights_all = FeatureWeights(
            spectral_centroid=1.0, spectral_bandwidth=1.0, spectral_rolloff=1.0,
            spectral_contrast=1.0, spectral_flatness=1.0, zero_crossing_rate=1.0,
            rms_energy=1.0, chroma_mean=1.0, tonnetz_mean=1.0, mfcc_mean=1.0, tempo=1.0
        )
        
        weights_selective = FeatureWeights(spectral_centroid=1.0, rms_energy=1.0)
        
        try:
            import time
            
            # Time full feature extraction
            start_time = time.time()
            features_all = extractor.extract_scalar_features(audio_file, weights_all)
            time_all = time.time() - start_time
            
            # Time selective feature extraction
            start_time = time.time()
            features_selective = extractor.extract_scalar_features(audio_file, weights_selective)
            time_selective = time.time() - start_time
            
            # Selective extraction should be faster (allow some tolerance)
            assert time_selective <= time_all + 0.1  # Add small tolerance for timing variations
            
            # Verify that selective extraction produced expected results
            assert features_selective.spectral_centroid > 0
            assert features_selective.rms_energy > 0
            assert features_selective.spectral_bandwidth == 0.0  # Not computed
            
        finally:
            audio_file.unlink()

    def test_feature_normalization(self, extractor):
        """Test the private feature normalization method."""
        features = ScalarFeatures(
            spectral_centroid=1000.0,
            rms_energy=0.5,
            tempo=120.0
        )
        
        normalization_params = {
            'spectral_centroid': {'mean': 800.0, 'std': 200.0},
            'rms_energy': {'mean': 0.3, 'std': 0.1},
            'tempo': {'mean': 120.0, 'std': 20.0}
        }
        
        normalized = extractor._normalize_features(features, normalization_params)
        
        # Check normalized values
        assert abs(normalized.spectral_centroid - 1.0) < 1e-6  # (1000-800)/200 = 1.0
        assert abs(normalized.rms_energy - 2.0) < 1e-6  # (0.5-0.3)/0.1 = 2.0
        assert abs(normalized.tempo - 0.0) < 1e-6  # (120-120)/20 = 0.0

    def test_edge_case_very_short_audio(self, extractor, feature_weights_all_active):
        """Test feature extraction from very short audio files."""
        # Create very short audio (0.1 seconds)
        audio_file = self.create_test_audio_file(duration=0.1)
        
        try:
            features = extractor.extract_scalar_features(audio_file, feature_weights_all_active)
            
            # Should still extract features without error
            assert isinstance(features, ScalarFeatures)
            # Most features should be non-zero for a sine wave
            assert features.rms_energy > 0
            
        finally:
            audio_file.unlink()

    def test_edge_case_silent_audio(self, extractor, feature_weights_all_active):
        """Test feature extraction from silent audio."""
        # Create silent audio
        t = np.linspace(0, 1.0, 44100, False)
        audio = np.zeros_like(t)  # Silent
        
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        sf.write(temp_file.name, audio, 44100)
        temp_file.close()
        audio_file = Path(temp_file.name)
        
        try:
            features = extractor.extract_scalar_features(audio_file, feature_weights_all_active)
            
            # Silent audio should have minimal features
            assert features.rms_energy < 1e-6  # Very low energy
            assert features.zero_crossing_rate < 1e-6  # No crossings
            
        finally:
            audio_file.unlink()


@pytest.mark.performance
class TestLibrosaFeatureExtractorPerformance:
    """Performance tests for LibrosaFeatureExtractor."""

    def test_large_audio_file_performance(self):
        """Test performance with larger audio files."""
        extractor = LibrosaFeatureExtractor()
        weights = FeatureWeights(spectral_centroid=1.0, rms_energy=1.0, tempo=1.0)
        
        # Create longer audio file (30 seconds)
        duration = 30.0
        sample_rate = 44100
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        audio = 0.3 * np.sin(2 * np.pi * 440 * t)
        
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        sf.write(temp_file.name, audio, sample_rate)
        temp_file.close()
        audio_file = Path(temp_file.name)
        
        try:
            import time
            start_time = time.time()
            features = extractor.extract_scalar_features(audio_file, weights)
            extraction_time = time.time() - start_time
            
            # Should complete within reasonable time (adjust threshold as needed)
            assert extraction_time < 10.0  # 10 seconds max for 30-second audio
            assert features.spectral_centroid > 0
            
        finally:
            audio_file.unlink()

    def test_batch_processing_performance(self):
        """Test performance when processing multiple files in sequence."""
        extractor = LibrosaFeatureExtractor()
        weights = FeatureWeights(spectral_centroid=1.0, rms_energy=1.0)
        
        # Create multiple small test files
        audio_files = []
        try:
            for i in range(5):
                t = np.linspace(0, 1.0, 44100, False)
                freq = 440 + i * 100  # Different frequencies
                audio = 0.3 * np.sin(2 * np.pi * freq * t)
                
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
                sf.write(temp_file.name, audio, 44100)
                temp_file.close()
                audio_files.append(Path(temp_file.name))
            
            # Process all files and measure time
            import time
            start_time = time.time()
            
            features_list = []
            for audio_file in audio_files:
                features = extractor.extract_scalar_features(audio_file, weights)
                features_list.append(features)
            
            total_time = time.time() - start_time
            
            # Should complete batch processing efficiently
            assert total_time < 5.0  # 5 seconds max for 5 files
            assert len(features_list) == 5
            
            # Each file should have different spectral centroid
            centroids = [f.spectral_centroid for f in features_list]
            assert len(set(centroids)) > 1  # Should have different values
            
        finally:
            for audio_file in audio_files:
                if audio_file.exists():
                    audio_file.unlink()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])