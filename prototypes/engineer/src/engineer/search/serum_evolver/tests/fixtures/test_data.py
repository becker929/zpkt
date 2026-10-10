"""
Test data generation utilities for SerumeEvolver testing.

This module provides functions to generate various test datasets including
parameters, features, and audio data for comprehensive testing scenarios.
"""

import numpy as np
from typing import Dict, List, Tuple, Any
from dataclasses import dataclass
from pathlib import Path
import json
import tempfile

from serum_evolver.interfaces import SerumParameters, ParameterConstraintSet, ScalarFeatures, FeatureWeights


# =============================================================================
# Parameter Test Data Generation
# =============================================================================

class ParameterTestDataGenerator:
    """Generate parameter-related test data."""
    
    COMMON_SERUM_PARAMS = {
        "1": ("MasterVol", 0.0, 1.0),
        "4": ("A Octave", 0.0, 1.0), 
        "5": ("A Fine", 0.0, 1.0),
        "6": ("A Pan", 0.0, 1.0),
        "7": ("A Level", 0.0, 1.0),
        "10": ("OSC A WT Pos", 0.0, 1.0),
        "11": ("OSC A Sub", 0.0, 1.0),
        "15": ("OSC A Sync", 0.0, 1.0),
        "20": ("Filter 1 Cutoff", 0.0, 1.0),
        "21": ("Filter 1 Resonance", 0.0, 1.0)
    }
    
    @classmethod
    def generate_fx_parameters_data(cls, param_count: int = None) -> Dict[str, Any]:
        """Generate mock fx_parameters.json data structure."""
        if param_count is None:
            params_to_use = cls.COMMON_SERUM_PARAMS
        else:
            # Generate specified number of parameters
            params_to_use = {}
            param_ids = list(cls.COMMON_SERUM_PARAMS.keys())[:param_count]
            for param_id in param_ids:
                params_to_use[param_id] = cls.COMMON_SERUM_PARAMS[param_id]
            
            # Fill remaining with generated parameters
            for i in range(len(param_ids), param_count):
                param_id = str(i + 1)
                param_name = f"Generated Param {i + 1}"
                params_to_use[param_id] = (param_name, 0.0, 1.0)
        
        parameters = {}
        for param_id, (name, min_val, max_val) in params_to_use.items():
            parameters[param_id] = {
                "formatted_value": f" {int((min_val + max_val) / 2 * 100)}%",
                "identifier": f"{int(param_id)-1}:{int(param_id)-1}",
                "max_value": max_val,
                "mid_value": (min_val + max_val) / 2,
                "min_value": min_val,
                "name": name,
                "normalized_value": (min_val + max_val) / 2,
                "value": (min_val + max_val) / 2
            }
        
        return {
            "fx_data": {
                "Serum_Track_VST3i:_Serum_Xfer_Records": {
                    "name": "VST3i: Serum (Xfer Records)",
                    "param_count": len(parameters),
                    "parameters": parameters
                }
            }
        }
    
    @classmethod
    def generate_constraint_sets(cls) -> Dict[str, ParameterConstraintSet]:
        """Generate various constraint sets for testing."""
        return {
            "single_param": {"4": (0.2, 0.8)},
            
            "small_set": {
                "1": (0.3, 0.9),
                "4": (0.1, 0.7),
                "7": (0.4, 0.8)
            },
            
            "medium_set": {
                "1": (0.2, 0.8),
                "4": (0.1, 0.9),
                "5": (0.3, 0.7),
                "6": (0.0, 1.0),
                "7": (0.4, 0.6),
                "10": (0.2, 0.9)
            },
            
            "large_set": {
                str(i): (np.random.uniform(0.0, 0.3), np.random.uniform(0.7, 1.0))
                for i in range(1, 21)  # 20 parameters
            },
            
            "stress_test": {
                str(i): (np.random.uniform(0.0, 0.4), np.random.uniform(0.6, 1.0))
                for i in range(1, 51)  # 50 parameters
            },
            
            "edge_case_tight": {
                "4": (0.45, 0.55),  # Very tight constraint
                "7": (0.75, 0.85)
            },
            
            "edge_case_full_range": {
                "1": (0.0, 1.0),
                "4": (0.0, 1.0),
                "5": (0.0, 1.0)
            }
        }
    
    @classmethod
    def generate_random_parameters(cls, constraint_set: ParameterConstraintSet) -> SerumParameters:
        """Generate random parameter values within constraints."""
        return {
            param_id: np.random.uniform(min_val, max_val)
            for param_id, (min_val, max_val) in constraint_set.items()
        }


# =============================================================================
# Feature Test Data Generation  
# =============================================================================

class FeatureTestDataGenerator:
    """Generate feature-related test data."""
    
    @classmethod
    def generate_feature_sets(cls) -> Dict[str, Tuple[ScalarFeatures, FeatureWeights]]:
        """Generate various feature target and weight combinations."""
        return {
            "basic_spectral": (
                ScalarFeatures(
                    spectral_centroid=2000.0,
                    spectral_bandwidth=1500.0,
                    rms_energy=0.1
                ),
                FeatureWeights(
                    spectral_centroid=1.0,
                    spectral_bandwidth=0.8,
                    rms_energy=0.6
                )
            ),
            
            "bright_sound": (
                ScalarFeatures(
                    spectral_centroid=4000.0,
                    spectral_rolloff=6000.0,
                    spectral_contrast=0.8,
                    rms_energy=0.15
                ),
                FeatureWeights(
                    spectral_centroid=1.0,
                    spectral_rolloff=0.9,
                    spectral_contrast=0.7,
                    rms_energy=0.5
                )
            ),
            
            "dark_sound": (
                ScalarFeatures(
                    spectral_centroid=800.0,
                    spectral_rolloff=1500.0,
                    spectral_flatness=0.2,
                    rms_energy=0.2
                ),
                FeatureWeights(
                    spectral_centroid=1.0,
                    spectral_rolloff=0.8,
                    spectral_flatness=0.6,
                    rms_energy=0.7
                )
            ),
            
            "harmonic_focus": (
                ScalarFeatures(
                    chroma_mean=0.8,
                    tonnetz_mean=0.6,
                    spectral_contrast=0.7,
                    rms_energy=0.12
                ),
                FeatureWeights(
                    chroma_mean=1.0,
                    tonnetz_mean=0.9,
                    spectral_contrast=0.6,
                    rms_energy=0.4
                )
            ),
            
            "rhythm_focus": (
                ScalarFeatures(
                    zero_crossing_rate=0.15,
                    tempo=120.0,
                    rms_energy=0.18
                ),
                FeatureWeights(
                    zero_crossing_rate=1.0,
                    tempo=0.8,
                    rms_energy=0.9
                )
            ),
            
            "all_features": (
                ScalarFeatures(
                    spectral_centroid=2500.0,
                    spectral_bandwidth=1800.0,
                    spectral_rolloff=4000.0,
                    spectral_contrast=0.6,
                    spectral_flatness=0.4,
                    zero_crossing_rate=0.1,
                    rms_energy=0.15,
                    chroma_mean=0.7,
                    tonnetz_mean=0.5,
                    mfcc_mean=12.0,
                    tempo=140.0
                ),
                FeatureWeights(
                    spectral_centroid=1.0,
                    spectral_bandwidth=0.9,
                    spectral_rolloff=0.8,
                    spectral_contrast=0.7,
                    spectral_flatness=0.6,
                    zero_crossing_rate=0.5,
                    rms_energy=0.8,
                    chroma_mean=0.6,
                    tonnetz_mean=0.4,
                    mfcc_mean=0.3,
                    tempo=0.2
                )
            )
        }
    
    @classmethod
    def generate_realistic_features(cls, sound_type: str) -> ScalarFeatures:
        """Generate realistic feature values for different sound types."""
        if sound_type == "bass":
            return ScalarFeatures(
                spectral_centroid=np.random.uniform(200, 800),
                spectral_bandwidth=np.random.uniform(400, 1200),
                spectral_rolloff=np.random.uniform(500, 1500),
                spectral_contrast=np.random.uniform(0.3, 0.7),
                spectral_flatness=np.random.uniform(0.1, 0.4),
                zero_crossing_rate=np.random.uniform(0.02, 0.08),
                rms_energy=np.random.uniform(0.1, 0.3),
                chroma_mean=np.random.uniform(0.4, 0.8),
                tonnetz_mean=np.random.uniform(0.3, 0.7),
                mfcc_mean=np.random.uniform(-5, 5),
                tempo=np.random.uniform(60, 140)
            )
        
        elif sound_type == "lead":
            return ScalarFeatures(
                spectral_centroid=np.random.uniform(1500, 4000),
                spectral_bandwidth=np.random.uniform(1200, 2500),
                spectral_rolloff=np.random.uniform(2000, 6000),
                spectral_contrast=np.random.uniform(0.5, 0.9),
                spectral_flatness=np.random.uniform(0.2, 0.6),
                zero_crossing_rate=np.random.uniform(0.08, 0.15),
                rms_energy=np.random.uniform(0.05, 0.2),
                chroma_mean=np.random.uniform(0.6, 0.9),
                tonnetz_mean=np.random.uniform(0.4, 0.8),
                mfcc_mean=np.random.uniform(5, 20),
                tempo=np.random.uniform(80, 160)
            )
        
        elif sound_type == "pad":
            return ScalarFeatures(
                spectral_centroid=np.random.uniform(800, 2500),
                spectral_bandwidth=np.random.uniform(600, 2000),
                spectral_rolloff=np.random.uniform(1000, 4000),
                spectral_contrast=np.random.uniform(0.2, 0.6),
                spectral_flatness=np.random.uniform(0.3, 0.7),
                zero_crossing_rate=np.random.uniform(0.05, 0.12),
                rms_energy=np.random.uniform(0.02, 0.15),
                chroma_mean=np.random.uniform(0.7, 0.95),
                tonnetz_mean=np.random.uniform(0.6, 0.9),
                mfcc_mean=np.random.uniform(0, 15),
                tempo=np.random.uniform(60, 120)
            )
        
        else:  # generic/random
            return ScalarFeatures(
                spectral_centroid=np.random.uniform(500, 3000),
                spectral_bandwidth=np.random.uniform(800, 2200),
                spectral_rolloff=np.random.uniform(1000, 5000),
                spectral_contrast=np.random.uniform(0.3, 0.8),
                spectral_flatness=np.random.uniform(0.2, 0.6),
                zero_crossing_rate=np.random.uniform(0.05, 0.15),
                rms_energy=np.random.uniform(0.05, 0.25),
                chroma_mean=np.random.uniform(0.3, 0.9),
                tonnetz_mean=np.random.uniform(0.2, 0.8),
                mfcc_mean=np.random.uniform(-10, 25),
                tempo=np.random.uniform(60, 180)
            )


# =============================================================================
# Evolution Test Data Generation
# =============================================================================

class EvolutionTestDataGenerator:
    """Generate test data for evolution scenarios."""
    
    @classmethod
    def generate_test_scenarios(cls) -> Dict[str, Dict[str, Any]]:
        """Generate complete test scenarios for evolution testing."""
        param_gen = ParameterTestDataGenerator()
        feature_gen = FeatureTestDataGenerator()
        
        constraint_sets = param_gen.generate_constraint_sets()
        feature_sets = feature_gen.generate_feature_sets()
        
        return {
            "basic_evolution": {
                "constraint_set": constraint_sets["single_param"],
                "target_features": feature_sets["basic_spectral"][0],
                "feature_weights": feature_sets["basic_spectral"][1],
                "n_generations": 3,
                "population_size": 4,
                "expected_time": 10.0  # seconds
            },
            
            "medium_complexity": {
                "constraint_set": constraint_sets["medium_set"],
                "target_features": feature_sets["bright_sound"][0],
                "feature_weights": feature_sets["bright_sound"][1],
                "n_generations": 5,
                "population_size": 8,
                "expected_time": 30.0
            },
            
            "high_complexity": {
                "constraint_set": constraint_sets["large_set"],
                "target_features": feature_sets["all_features"][0],
                "feature_weights": feature_sets["all_features"][1],
                "n_generations": 10,
                "population_size": 12,
                "expected_time": 60.0
            },
            
            "stress_test": {
                "constraint_set": constraint_sets["stress_test"],
                "target_features": feature_sets["all_features"][0],
                "feature_weights": feature_sets["all_features"][1],
                "n_generations": 15,
                "population_size": 16,
                "expected_time": 120.0
            },
            
            "convergence_test": {
                "constraint_set": constraint_sets["small_set"],
                "target_features": feature_sets["harmonic_focus"][0],
                "feature_weights": feature_sets["harmonic_focus"][1],
                "n_generations": 20,
                "population_size": 6,
                "expected_time": 45.0
            }
        }


# =============================================================================
# File and Configuration Utilities
# =============================================================================

def create_temporary_fx_params(param_count: int = 10) -> Path:
    """Create a temporary fx_parameters.json file."""
    data = ParameterTestDataGenerator.generate_fx_parameters_data(param_count)
    
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    json.dump(data, temp_file, indent=2)
    temp_file.close()
    
    return Path(temp_file.name)


def create_test_session_config(session_name: str, parameters: SerumParameters) -> Dict[str, Any]:
    """Create a test session configuration."""
    return {
        "session_name": session_name,
        "render_configs": [
            {
                "render_id": f"{session_name}_render",
                "tracks": ["Track 1"],
                "parameters": [
                    {"param_id": param_id, "value": value}
                    for param_id, value in parameters.items()
                ],
                "midi_files": ["test_melody.mid"],
                "render_options": {
                    "bpm": 148,
                    "note": "C4",
                    "duration": "whole"
                }
            }
        ]
    }


# =============================================================================
# Benchmark Data Generation
# =============================================================================

class BenchmarkDataGenerator:
    """Generate data for performance benchmarking."""
    
    @classmethod
    def generate_performance_test_cases(cls) -> Dict[str, Dict[str, Any]]:
        """Generate test cases specifically designed for performance testing."""
        return {
            "small_population": {
                "constraint_set": {"1": (0.3, 0.7), "4": (0.2, 0.8)},
                "population_size": 4,
                "n_generations": 5,
                "expected_max_time": 15.0,
                "expected_max_memory_mb": 100
            },
            
            "medium_population": {
                "constraint_set": {str(i): (0.1, 0.9) for i in range(1, 8)},
                "population_size": 8,
                "n_generations": 10,
                "expected_max_time": 45.0,
                "expected_max_memory_mb": 200
            },
            
            "large_population": {
                "constraint_set": {str(i): (0.0, 1.0) for i in range(1, 16)},
                "population_size": 16,
                "n_generations": 15,
                "expected_max_time": 90.0,
                "expected_max_memory_mb": 500
            },
            
            "stress_population": {
                "constraint_set": {str(i): (np.random.uniform(0.0, 0.3), np.random.uniform(0.7, 1.0)) for i in range(1, 31)},
                "population_size": 24,
                "n_generations": 20,
                "expected_max_time": 150.0,
                "expected_max_memory_mb": 1000
            }
        }
    
    @classmethod 
    def generate_memory_stress_data(cls, size_mb: float) -> np.ndarray:
        """Generate data to stress test memory usage."""
        # Calculate array size for approximately the requested memory
        bytes_per_mb = 1024 * 1024
        float64_size = 8  # bytes
        array_size = int((size_mb * bytes_per_mb) / float64_size)
        
        return np.random.random(array_size)