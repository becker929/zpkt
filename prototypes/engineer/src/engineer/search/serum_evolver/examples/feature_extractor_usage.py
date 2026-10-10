#!/usr/bin/env python3
"""
Example usage of LibrosaFeatureExtractor for audio feature extraction.

This example demonstrates:
1. Creating a feature extractor
2. Setting up feature weights
3. Extracting features from audio
4. Computing distance between feature sets

Requirements:
- Audio files for testing (or synthetic audio generation)
- LibrosaFeatureExtractor implementation
"""

import sys
from pathlib import Path
import numpy as np
import soundfile as sf
import tempfile

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from serum_evolver import LibrosaFeatureExtractor, FeatureWeights, ScalarFeatures


def create_test_audio(duration=2.0, frequency=440.0, sample_rate=44100):
    """Create a test audio file with a sine wave."""
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    audio = 0.3 * np.sin(2 * np.pi * frequency * t)
    
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
    sf.write(temp_file.name, audio, sample_rate)
    temp_file.close()
    
    return Path(temp_file.name)


def example_basic_usage():
    """Demonstrate basic feature extraction."""
    print("=== Basic Feature Extraction ===")
    
    # Create feature extractor
    extractor = LibrosaFeatureExtractor(sample_rate=44100, hop_length=512)
    
    # Create feature weights - specify which features to extract
    weights = FeatureWeights(
        spectral_centroid=1.0,
        rms_energy=1.0,
        zero_crossing_rate=1.0,
        tempo=0.5  # Lower weight for tempo
    )
    
    # Create test audio
    audio_file = create_test_audio(frequency=880.0, duration=1.0)  # A4 note (880 Hz)
    
    try:
        # Extract features
        features = extractor.extract_scalar_features(audio_file, weights)
        
        print(f"Extracted features:")
        print(f"  Spectral Centroid: {features.spectral_centroid:.2f} Hz")
        print(f"  RMS Energy: {features.rms_energy:.4f}")
        print(f"  Zero Crossing Rate: {features.zero_crossing_rate:.4f}")
        print(f"  Tempo: {features.tempo:.1f} BPM")
        
        # Inactive features should be zero
        print(f"  Spectral Bandwidth (inactive): {features.spectral_bandwidth}")
        print(f"  Spectral Rolloff (inactive): {features.spectral_rolloff}")
        
    finally:
        audio_file.unlink()


def example_feature_comparison():
    """Demonstrate distance calculation between feature sets."""
    print("\n=== Feature Distance Calculation ===")
    
    extractor = LibrosaFeatureExtractor()
    
    # Define weights for comparison
    weights = FeatureWeights(
        spectral_centroid=1.0,
        spectral_bandwidth=0.5,
        rms_energy=2.0,  # Higher weight for energy differences
        tempo=0.1
    )
    
    # Create two different audio files
    audio1 = create_test_audio(frequency=440.0, duration=1.0)  # A4
    audio2 = create_test_audio(frequency=880.0, duration=1.0)  # A5 (octave higher)
    
    try:
        # Extract features from both files
        features1 = extractor.extract_scalar_features(audio1, weights)
        features2 = extractor.extract_scalar_features(audio2, weights)
        
        print(f"Features from 440 Hz sine:")
        print(f"  Spectral Centroid: {features1.spectral_centroid:.2f} Hz")
        print(f"  RMS Energy: {features1.rms_energy:.4f}")
        
        print(f"Features from 880 Hz sine:")
        print(f"  Spectral Centroid: {features2.spectral_centroid:.2f} Hz")
        print(f"  RMS Energy: {features2.rms_energy:.4f}")
        
        # Compute distance between feature sets
        distance = extractor.compute_feature_distance(features1, features2, weights)
        print(f"\nWeighted distance between feature sets: {distance:.4f}")
        
        # Compare with identical features (distance should be 0)
        distance_identical = extractor.compute_feature_distance(features1, features1, weights)
        print(f"Distance between identical features: {distance_identical:.4f}")
        
    finally:
        audio1.unlink()
        audio2.unlink()


def example_selective_extraction():
    """Demonstrate performance optimization with selective feature extraction."""
    print("\n=== Selective Feature Extraction ===")
    
    extractor = LibrosaFeatureExtractor()
    
    # Extract all features
    weights_all = FeatureWeights(
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
    
    # Extract only essential features
    weights_selective = FeatureWeights(
        spectral_centroid=1.0,
        rms_energy=1.0
    )
    
    audio_file = create_test_audio(frequency=440.0, duration=2.0)
    
    try:
        import time
        
        # Time full extraction
        start_time = time.time()
        features_all = extractor.extract_scalar_features(audio_file, weights_all)
        time_all = time.time() - start_time
        
        # Time selective extraction
        start_time = time.time()
        features_selective = extractor.extract_scalar_features(audio_file, weights_selective)
        time_selective = time.time() - start_time
        
        print(f"Full extraction (11 features): {time_all:.4f}s")
        print(f"Selective extraction (2 features): {time_selective:.4f}s")
        print(f"Speedup: {time_all / time_selective:.2f}x")
        
        print("\nFull feature set:")
        for feature_name in features_all.__dict__:
            value = getattr(features_all, feature_name)
            print(f"  {feature_name}: {value:.6f}")
        
        print("\nSelective feature set (non-zero values only):")
        for feature_name in features_selective.__dict__:
            value = getattr(features_selective, feature_name)
            if value != 0.0:
                print(f"  {feature_name}: {value:.6f}")
        
    finally:
        audio_file.unlink()


def example_error_handling():
    """Demonstrate error handling capabilities."""
    print("\n=== Error Handling ===")
    
    extractor = LibrosaFeatureExtractor()
    weights = FeatureWeights(spectral_centroid=1.0)
    
    # Test with non-existent file
    try:
        extractor.extract_scalar_features(Path("non_existent.wav"), weights)
    except FileNotFoundError as e:
        print(f"Caught expected error: {e}")
    
    # Test with no active features
    inactive_weights = FeatureWeights()  # All weights are 0.0
    audio_file = create_test_audio()
    
    try:
        features = extractor.extract_scalar_features(audio_file, inactive_weights)
        print(f"No active features - returned zero features: {all(getattr(features, attr) == 0.0 for attr in features.__dict__)}")
    finally:
        audio_file.unlink()


if __name__ == "__main__":
    print("LibrosaFeatureExtractor Usage Examples")
    print("=" * 50)
    
    example_basic_usage()
    example_feature_comparison()
    example_selective_extraction()
    example_error_handling()
    
    print("\n=== Examples Complete ===")
    print("The LibrosaFeatureExtractor is ready for use in evolutionary audio synthesis!")