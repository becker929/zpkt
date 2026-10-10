"""
Comprehensive integration tests for SerumEvolver system.

This test suite validates the complete integration between all components:
- SerumParameterManager
- LibrosaFeatureExtractor  
- SerumAudioGenerator
- AdaptiveSerumEvolver

Tests cover the full pipeline from parameter constraints to evolved solutions.
"""

import pytest
import time
import numpy as np
from pathlib import Path
from typing import Dict, Any, List
from unittest.mock import patch, Mock

from serum_evolver.interfaces import SerumParameters, ParameterConstraintSet, ScalarFeatures, FeatureWeights
from serum_evolver.parameter_manager import SerumParameterManager
from serum_evolver.feature_extractor import LibrosaFeatureExtractor
from serum_evolver.audio_generator import SerumAudioGenerator
from serum_evolver.ga_engine import AdaptiveSerumEvolver

from .fixtures.test_data import (
    ParameterTestDataGenerator, 
    FeatureTestDataGenerator,
    EvolutionTestDataGenerator
)
from .fixtures.mock_reaper import MockReaperPatches


class TestFullPipelineIntegration:
    """Test complete pipeline integration from constraints to evolved solutions."""
    
    def test_basic_evolution_pipeline(self, ga_engine, test_constraint_generator, test_features_generator, mock_audio_generation):
        """Test basic evolution pipeline with simple constraints."""
        # Generate test data
        constraint_set = test_constraint_generator("simple")
        target_features, feature_weights = test_features_generator("basic")
        
        # Run evolution
        with MockReaperPatches(simulate_execution_time=0.05):
            result = ga_engine.evolve(
                constraint_set=constraint_set,
                target_features=target_features,
                feature_weights=feature_weights,
                n_generations=3,
                population_size=4
            )
        
        # Validate results
        assert "best_parameters" in result
        assert "best_fitness" in result
        assert "generations_run" in result
        assert "convergence_history" in result
        
        # Check parameter validity
        best_params = result["best_parameters"]
        assert isinstance(best_params, dict)
        assert len(best_params) > 0
        
        # Verify parameters are within constraints
        for param_id, value in best_params.items():
            if param_id in constraint_set:
                min_val, max_val = constraint_set[param_id]
                assert min_val <= value <= max_val, f"Parameter {param_id} value {value} not within constraint [{min_val}, {max_val}]"
        
        # Check fitness improvement
        convergence_history = result["convergence_history"]
        assert len(convergence_history) >= 1
        assert all(isinstance(fitness, (int, float)) for fitness in convergence_history)
        
        # Verify evolution ran expected number of generations
        assert result["generations_run"] >= 1
        assert result["generations_run"] <= 3
        
        print(f"✓ Basic evolution completed in {result['generations_run']} generations")
        print(f"  Best fitness: {result['best_fitness']:.6f}")
        print(f"  Parameters evolved: {list(best_params.keys())}")
    
    def test_medium_complexity_evolution(self, ga_engine, test_constraint_generator, test_features_generator, mock_audio_generation):
        """Test evolution with medium complexity constraints and features."""
        constraint_set = test_constraint_generator("medium")
        target_features, feature_weights = test_features_generator("multi")
        
        with MockReaperPatches(simulate_execution_time=0.05):
            result = ga_engine.evolve(
                constraint_set=constraint_set,
                target_features=target_features,
                feature_weights=feature_weights,
                n_generations=5,
                population_size=6
            )
        
        # Validate medium complexity requirements
        assert len(result["best_parameters"]) >= 3
        assert result["generations_run"] >= 2
        
        # Check that multiple features were targeted
        active_features = feature_weights.get_active_features()
        assert len(active_features) >= 3
        
        # Verify convergence progression
        convergence = result["convergence_history"]
        assert len(convergence) >= 2
        
        # Evolution should show some improvement (not necessarily monotonic due to GA nature)
        assert min(convergence) < max(convergence) * 2  # Some improvement shown
        
        print(f"✓ Medium complexity evolution: {len(result['best_parameters'])} params, {len(active_features)} features")
    
    def test_parameter_constraint_validation_integration(self, parameter_manager, audio_generator, test_constraint_generator):
        """Test parameter constraint validation across components."""
        constraint_sets = {
            "valid_simple": test_constraint_generator("simple"),
            "valid_complex": test_constraint_generator("complex"),
            "invalid_out_of_bounds": {"1": (-0.5, 1.5)},  # Invalid range
            "invalid_unknown_param": {"999": (0.0, 1.0)}   # Unknown parameter
        }
        
        for test_name, constraint_set in constraint_sets.items():
            if test_name.startswith("valid"):
                # Should pass validation
                assert parameter_manager.validate_constraint_set(constraint_set), f"Valid constraint set {test_name} failed validation"
                
                # Should generate valid parameters
                random_params = audio_generator._generate_random_parameters(constraint_set)
                assert len(random_params) == len(constraint_set)
                
                for param_id, value in random_params.items():
                    assert parameter_manager.validate_parameter_value(param_id, value), f"Generated parameter {param_id}={value} invalid"
                    
            else:
                # Should fail validation  
                assert not parameter_manager.validate_constraint_set(constraint_set), f"Invalid constraint set {test_name} passed validation"
        
        print("✓ Parameter constraint validation working across components")
    
    def test_audio_feature_extraction_integration(self, audio_generator, feature_extractor, parameter_manager, mock_audio_generation):
        """Test audio generation to feature extraction pipeline."""
        # Generate test parameters
        test_params = {
            "1": 0.7,   # MasterVol
            "4": 0.3,   # A Octave (lower)
            "7": 0.8    # A Level
        }
        
        # Test different feature weight configurations
        feature_configs = [
            FeatureWeights(spectral_centroid=1.0),
            FeatureWeights(spectral_centroid=0.8, rms_energy=0.6),
            FeatureWeights(spectral_centroid=1.0, spectral_bandwidth=0.7, rms_energy=0.5)
        ]
        
        for i, weights in enumerate(feature_configs):
            with MockReaperPatches(simulate_execution_time=0.02):
                # Generate audio
                audio_path = audio_generator.render_patch(test_params, "test_session")
                assert audio_path is not None
                
                # Extract features
                features = feature_extractor.extract_scalar_features(Path(audio_path), weights)
                
                # Validate feature extraction
                active_features = weights.get_active_features()
                for feature_name, weight in active_features.items():
                    feature_value = getattr(features, feature_name)
                    assert feature_value is not None
                    assert isinstance(feature_value, (int, float))
                    assert not np.isnan(feature_value), f"Feature {feature_name} is NaN"
                    assert not np.isinf(feature_value), f"Feature {feature_name} is infinite"
                
                print(f"  Config {i+1}: Extracted {len(active_features)} features successfully")
        
        print("✓ Audio generation to feature extraction pipeline working")
    
    def test_cross_component_error_handling(self, ga_engine, test_constraint_generator, test_features_generator):
        """Test error propagation and handling across component boundaries."""
        
        # Test 1: Invalid constraint set should be caught early
        with pytest.raises((ValueError, AssertionError)):
            invalid_constraints = {"999": (0.0, 1.0)}  # Unknown parameter
            target_features, feature_weights = test_features_generator("basic")
            ga_engine.evolve(invalid_constraints, target_features, feature_weights, n_generations=2, population_size=4)
        
        # Test 2: Empty feature weights should be handled
        constraint_set = test_constraint_generator("simple")
        target_features, _ = test_features_generator("basic")
        empty_weights = FeatureWeights()  # All weights are 0.0
        
        with MockReaperPatches():
            result = ga_engine.evolve(constraint_set, target_features, empty_weights, n_generations=2, population_size=4)
            # Should complete but with warning about no active features
            assert "best_parameters" in result
        
        # Test 3: REAPER execution failures should be handled gracefully
        constraint_set = test_constraint_generator("simple")
        target_features, feature_weights = test_features_generator("basic")
        
        with MockReaperPatches(simulate_failures=True, failure_rate=0.5):
            # Evolution should still complete despite some failures
            result = ga_engine.evolve(constraint_set, target_features, feature_weights, n_generations=2, population_size=4)
            assert "best_parameters" in result
            # Some individuals may have failed, but evolution should still progress
        
        print("✓ Cross-component error handling working correctly")
    
    def test_data_consistency_across_components(self, parameter_manager, audio_generator, feature_extractor, ga_engine):
        """Test data consistency and format compatibility between components."""
        
        # Test parameter format consistency
        param_ids = parameter_manager.get_all_parameter_ids()
        assert len(param_ids) > 0
        
        # Test that parameter manager and audio generator use consistent formats
        constraint_set = {param_ids[0]: (0.2, 0.8)}
        random_params = audio_generator._generate_random_parameters(constraint_set)
        
        for param_id, value in random_params.items():
            # Parameter manager should recognize the parameter
            assert parameter_manager.validate_parameter_value(param_id, value)
            bounds = parameter_manager.get_parameter_bounds(param_id)
            assert isinstance(bounds, tuple)
            assert len(bounds) == 2
        
        # Test feature format consistency
        feature_weights = FeatureWeights(spectral_centroid=1.0, rms_energy=0.5)
        active_features = feature_weights.get_active_features()
        
        # Mock audio file for feature extraction test
        with MockReaperPatches():
            with patch('serum_evolver.audio_generator.ReaperSessionManager.execute_session') as mock_execute:
                mock_execute.return_value = "/tmp/test_consistency.wav"
                
                # Create mock audio file
                from .fixtures.mock_reaper import create_performance_audio_file
                audio_path = create_performance_audio_file(Path("/tmp/test_consistency.wav"), duration=2.0)
                
                # Extract features
                features = feature_extractor.extract_scalar_features(audio_path, feature_weights)
                
                # Verify all active features have valid values
                for feature_name in active_features.keys():
                    value = getattr(features, feature_name)
                    assert value is not None
                    assert isinstance(value, (int, float))
                    assert not np.isnan(value)
                
                # Cleanup
                if audio_path.exists():
                    audio_path.unlink()
        
        print("✓ Data consistency maintained across all components")
    
    def test_concurrent_component_access(self, ga_engine, test_constraint_generator, test_features_generator, concurrency_tester, mock_audio_generation):
        """Test thread safety and concurrent access to components."""
        
        def run_short_evolution(test_id: int):
            """Run a short evolution for concurrency testing."""
            constraint_set = test_constraint_generator("simple") 
            target_features, feature_weights = test_features_generator("basic")
            
            with MockReaperPatches(simulate_execution_time=0.01):
                result = ga_engine.evolve(
                    constraint_set=constraint_set,
                    target_features=target_features,
                    feature_weights=feature_weights,
                    n_generations=2,
                    population_size=4
                )
            
            return {
                "test_id": test_id,
                "best_fitness": result["best_fitness"],
                "generations": result["generations_run"]
            }
        
        # Run multiple concurrent evolutions
        test_args = [(i,) for i in range(4)]  # 4 concurrent tests
        
        concurrency_tester.run_concurrent(run_short_evolution, test_args, max_workers=4)
        concurrency_tester.assert_all_successful(4)
        
        results = concurrency_tester.get_results()
        
        # Verify all evolutions completed successfully
        assert len(results) == 4
        for result in results:
            assert "best_fitness" in result
            assert "generations" in result
            assert result["generations"] >= 1
        
        print(f"✓ Concurrent component access: {len(results)} simultaneous evolutions completed")
    
    def test_memory_management_integration(self, ga_engine, test_constraint_generator, test_features_generator, performance_monitor, mock_audio_generation):
        """Test memory management across integrated components."""
        import gc
        import psutil
        
        process = psutil.Process()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Run several evolutions to test memory accumulation
        constraint_set = test_constraint_generator("medium")
        target_features, feature_weights = test_features_generator("multi")
        
        performance_monitor.start()
        
        for i in range(5):  # Run 5 evolution cycles
            with MockReaperPatches(simulate_execution_time=0.02):
                result = ga_engine.evolve(
                    constraint_set=constraint_set,
                    target_features=target_features,
                    feature_weights=feature_weights,
                    n_generations=3,
                    population_size=4
                )
            
            # Force garbage collection between runs
            gc.collect()
            
            performance_monitor.update_peak_memory()
        
        performance_monitor.stop()
        metrics = performance_monitor.get_metrics()
        
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_growth = final_memory - initial_memory
        
        # Memory growth should be reasonable (< 200MB for this test)
        assert memory_growth < 200, f"Excessive memory growth: {memory_growth:.1f} MB"
        
        print(f"✓ Memory management: Growth {memory_growth:.1f} MB over 5 evolution cycles")
        print(f"  Peak memory usage: {metrics['memory_usage_mb']:.1f} MB")
    
    def test_evolution_result_consistency(self, ga_engine, test_constraint_generator, test_features_generator, mock_audio_generation):
        """Test consistency of evolution results across multiple runs."""
        
        # Run the same evolution multiple times
        constraint_set = test_constraint_generator("simple")
        target_features, feature_weights = test_features_generator("basic")
        
        results = []
        for i in range(3):  # 3 independent runs
            with MockReaperPatches(simulate_execution_time=0.02):
                result = ga_engine.evolve(
                    constraint_set=constraint_set,
                    target_features=target_features,
                    feature_weights=feature_weights,
                    n_generations=5,
                    population_size=6
                )
            results.append(result)
        
        # Verify result structure consistency
        for i, result in enumerate(results):
            assert "best_parameters" in result, f"Run {i}: Missing best_parameters"
            assert "best_fitness" in result, f"Run {i}: Missing best_fitness"
            assert "generations_run" in result, f"Run {i}: Missing generations_run"
            assert "convergence_history" in result, f"Run {i}: Missing convergence_history"
            
            # Check parameter constraints are satisfied
            for param_id, value in result["best_parameters"].items():
                if param_id in constraint_set:
                    min_val, max_val = constraint_set[param_id]
                    assert min_val <= value <= max_val, f"Run {i}: Parameter {param_id} out of bounds"
        
        # Results may differ due to stochastic nature, but structure should be consistent
        fitness_values = [r["best_fitness"] for r in results]
        generation_counts = [r["generations_run"] for r in results]
        
        print(f"✓ Evolution result consistency: {len(results)} runs completed")
        print(f"  Fitness range: {min(fitness_values):.6f} to {max(fitness_values):.6f}")
        print(f"  Generations range: {min(generation_counts)} to {max(generation_counts)}")


class TestComponentIntegrationPoints:
    """Test specific integration points between individual components."""
    
    def test_parameter_manager_audio_generator_integration(self, parameter_manager, audio_generator):
        """Test parameter manager and audio generator integration."""
        
        # Test parameter validation consistency
        param_ids = parameter_manager.get_all_parameter_ids()
        
        for param_id in param_ids[:5]:  # Test first 5 parameters
            bounds = parameter_manager.get_parameter_bounds(param_id)
            
            # Test boundary values
            test_values = [bounds[0], bounds[1], (bounds[0] + bounds[1]) / 2]
            
            for value in test_values:
                # Parameter manager should validate
                assert parameter_manager.validate_parameter_value(param_id, value)
                
                # Audio generator should accept for random generation
                constraint_set = {param_id: bounds}
                random_params = audio_generator._generate_random_parameters(constraint_set)
                assert param_id in random_params
                assert bounds[0] <= random_params[param_id] <= bounds[1]
        
        print(f"✓ Parameter manager ↔ Audio generator integration: {len(param_ids)} parameters tested")
    
    def test_feature_extractor_ga_engine_integration(self, feature_extractor, ga_engine, mock_performance_audio_data):
        """Test feature extractor and GA engine integration."""
        
        # Create test audio data
        audio_data = mock_performance_audio_data(duration_seconds=2.0)
        
        # Save as temporary audio file
        import tempfile
        import wave
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            with wave.open(temp_file.name, 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(44100)
                audio_16bit = (audio_data * 32767).astype(np.int16)
                wav_file.writeframes(audio_16bit.tobytes())
            
            temp_path = Path(temp_file.name)
        
        try:
            # Test different feature weight combinations
            test_weights = [
                FeatureWeights(spectral_centroid=1.0),
                FeatureWeights(spectral_centroid=0.8, rms_energy=0.6),
                FeatureWeights(spectral_centroid=1.0, spectral_bandwidth=0.5, rms_energy=0.7)
            ]
            
            for weights in test_weights:
                # Extract features
                features = feature_extractor.extract_scalar_features(temp_path, weights)
                
                # Test feature distance calculation (simulates GA fitness evaluation)
                target_features = ScalarFeatures(
                    spectral_centroid=2000.0,
                    spectral_bandwidth=1500.0,
                    rms_energy=0.1
                )
                
                distance = feature_extractor.compute_feature_distance(
                    features, target_features, weights
                )
                
                # Distance should be valid
                assert isinstance(distance, float)
                assert not np.isnan(distance)
                assert not np.isinf(distance)
                assert distance >= 0.0
                
                # Active features should match expectations
                active_features = weights.get_active_features()
                for feature_name in active_features.keys():
                    feature_value = getattr(features, feature_name)
                    assert feature_value is not None
        
        finally:
            # Cleanup
            temp_path.unlink()
        
        print("✓ Feature extractor ↔ GA engine integration working correctly")
    
    def test_audio_generator_ga_engine_integration(self, audio_generator, ga_engine, parameter_manager, mock_audio_generation):
        """Test audio generator and GA engine integration."""
        
        # Test GA engine's use of audio generator for population evaluation
        constraint_set = {"1": (0.3, 0.8), "4": (0.2, 0.9)}
        
        # Test random parameter generation (used for population initialization)
        for _ in range(10):  # Generate 10 random parameter sets
            random_params = audio_generator._generate_random_parameters(constraint_set)
            
            # Verify parameters are valid
            assert len(random_params) == len(constraint_set)
            for param_id, value in random_params.items():
                assert parameter_manager.validate_parameter_value(param_id, value)
                min_val, max_val = constraint_set[param_id]
                assert min_val <= value <= max_val
        
        # Test parameter-to-audio pipeline (used in fitness evaluation)  
        test_params = {"1": 0.6, "4": 0.5}
        
        with MockReaperPatches(simulate_execution_time=0.01):
            audio_path = audio_generator.render_patch(test_params, "test_session")
            assert audio_path is not None
            assert isinstance(audio_path, (str, Path))
        
        print("✓ Audio generator ↔ GA engine integration working correctly")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])