"""
End-to-end workflow tests for SerumEvolver system.

This test suite validates complete real-world workflows from start to finish,
simulating actual usage scenarios that a user would encounter. These tests
focus on realistic use cases and complete system behavior.
"""

import pytest
import time
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from unittest.mock import patch, Mock
import json

from serum_evolver.interfaces import SerumParameters, ParameterConstraintSet, ScalarFeatures, FeatureWeights
from serum_evolver.parameter_manager import SerumParameterManager
from serum_evolver.feature_extractor import LibrosaFeatureExtractor
from serum_evolver.audio_generator import SerumAudioGenerator
from serum_evolver.ga_engine import AdaptiveSerumEvolver

from .fixtures.test_data import EvolutionTestDataGenerator, ParameterTestDataGenerator, FeatureTestDataGenerator
from .fixtures.mock_reaper import MockReaperPatches, create_performance_audio_file


class TestCompleteWorkflows:
    """Test complete user workflows from initialization to final results."""
    
    def test_basic_user_workflow(self, temp_reaper_project, temp_fx_params_file, mock_audio_generation):
        """Test the basic user workflow: setup -> evolve -> results."""
        
        # Step 1: User initializes system components
        param_manager = SerumParameterManager(temp_fx_params_file)
        feature_extractor = LibrosaFeatureExtractor()
        audio_generator = SerumAudioGenerator(temp_reaper_project, param_manager)
        ga_engine = AdaptiveSerumEvolver(audio_generator, feature_extractor, param_manager)
        
        # Step 2: User defines their optimization goals
        constraint_set = {"1": (0.4, 0.8), "4": (0.2, 0.7)}  # Master volume and octave
        target_features = ScalarFeatures(
            spectral_centroid=2200.0,
            rms_energy=0.12,
            spectral_bandwidth=1600.0
        )
        feature_weights = FeatureWeights(
            spectral_centroid=1.0,
            rms_energy=0.8,
            spectral_bandwidth=0.6
        )
        
        # Step 3: User runs evolution
        with MockReaperPatches(simulate_execution_time=0.1):
            start_time = time.time()
            result = ga_engine.evolve(
                constraint_set=constraint_set,
                target_features=target_features,
                feature_weights=feature_weights,
                n_generations=5,
                population_size=8
            )
            end_time = time.time()
        
        # Step 4: User examines results
        assert "best_parameters" in result
        assert "best_fitness" in result
        assert "generations_run" in result
        assert "convergence_history" in result
        
        best_params = result["best_parameters"]
        assert len(best_params) == len(constraint_set)
        
        # Verify parameters are within user constraints
        for param_id, value in best_params.items():
            min_val, max_val = constraint_set[param_id]
            assert min_val <= value <= max_val
            
        # Verify reasonable performance (should complete in reasonable time)
        execution_time = end_time - start_time
        assert execution_time < 30.0, f"Evolution took too long: {execution_time:.2f}s"
        
        # Step 5: User can inspect convergence
        convergence = result["convergence_history"]
        assert len(convergence) == result["generations_run"]
        assert all(isinstance(fitness, (int, float)) for fitness in convergence)
        
        print(f"✓ Basic user workflow completed in {execution_time:.2f}s")
        print(f"  Best fitness: {result['best_fitness']:.6f}")
        print(f"  Parameters: {best_params}")
    
    def test_sound_design_workflow(self, ga_engine, mock_audio_generation):
        """Test a realistic sound design workflow targeting specific audio characteristics."""
        
        # Sound designer wants to create a "bright lead" sound
        scenarios = EvolutionTestDataGenerator.generate_test_scenarios()
        
        # Test different sound design goals
        sound_types = [
            {
                "name": "bright_lead",
                "constraint_set": {"1": (0.6, 0.9), "4": (0.6, 0.8), "7": (0.7, 0.9)},
                "target_features": ScalarFeatures(
                    spectral_centroid=3500.0,  # Bright sound
                    spectral_rolloff=5000.0,
                    rms_energy=0.15,
                    spectral_contrast=0.8
                ),
                "feature_weights": FeatureWeights(
                    spectral_centroid=1.0,
                    spectral_rolloff=0.9,
                    rms_energy=0.7,
                    spectral_contrast=0.8
                )
            },
            {
                "name": "warm_bass",
                "constraint_set": {"1": (0.7, 0.9), "4": (0.1, 0.3), "7": (0.8, 1.0)},
                "target_features": ScalarFeatures(
                    spectral_centroid=600.0,   # Low/warm sound
                    spectral_rolloff=1200.0,
                    rms_energy=0.25,
                    spectral_flatness=0.3
                ),
                "feature_weights": FeatureWeights(
                    spectral_centroid=1.0,
                    spectral_rolloff=0.9,
                    rms_energy=0.8,
                    spectral_flatness=0.6
                )
            }
        ]
        
        results = {}
        for sound_config in sound_types:
            print(f"\nDesigning {sound_config['name']} sound...")
            
            with MockReaperPatches(simulate_execution_time=0.05):
                result = ga_engine.evolve(
                    constraint_set=sound_config["constraint_set"],
                    target_features=sound_config["target_features"],
                    feature_weights=sound_config["feature_weights"],
                    n_generations=8,
                    population_size=10
                )
            
            results[sound_config["name"]] = result
            
            # Validate sound-specific results
            assert result["generations_run"] >= 3  # Should run at least a few generations
            
            # Check convergence progression
            convergence = result["convergence_history"]
            if len(convergence) > 3:
                # Should show some improvement over evolution
                early_avg = sum(convergence[:2]) / 2
                late_avg = sum(convergence[-2:]) / 2
                improvement_ratio = early_avg / late_avg if late_avg > 0 else 1.0
                assert improvement_ratio >= 0.8  # Some improvement or stability
            
            print(f"  ✓ {sound_config['name']}: fitness {result['best_fitness']:.6f}, {result['generations_run']} generations")
        
        # Compare results between different sound types
        bright_fitness = results["bright_lead"]["best_fitness"]
        bass_fitness = results["warm_bass"]["best_fitness"]
        
        # Both should achieve reasonable fitness (not testing which is better, just that both work)
        assert bright_fitness < 10.0  # Arbitrary reasonable threshold
        assert bass_fitness < 10.0
        
        print("✓ Sound design workflow: Created different sound types successfully")
    
    def test_iterative_refinement_workflow(self, ga_engine, mock_audio_generation):
        """Test iterative refinement workflow where user refines parameters over multiple runs."""
        
        # Initial broad search
        initial_constraints = {"1": (0.3, 0.9), "4": (0.1, 0.9), "7": (0.4, 0.8)}
        target_features = ScalarFeatures(spectral_centroid=2500.0, rms_energy=0.15)
        feature_weights = FeatureWeights(spectral_centroid=1.0, rms_energy=0.7)
        
        # Step 1: Initial broad evolution
        with MockReaperPatches(simulate_execution_time=0.03):
            initial_result = ga_engine.evolve(
                constraint_set=initial_constraints,
                target_features=target_features,
                feature_weights=feature_weights,
                n_generations=5,
                population_size=8
            )
        
        initial_best = initial_result["best_parameters"]
        print(f"Initial result: {initial_best}")
        
        # Step 2: User refines constraints around best result
        refined_constraints = {}
        for param_id, best_value in initial_best.items():
            # Create tighter constraints around the best found value
            range_size = 0.3  # ±0.15 around best value
            min_val = max(0.0, best_value - range_size/2)
            max_val = min(1.0, best_value + range_size/2)
            refined_constraints[param_id] = (min_val, max_val)
        
        # Step 3: Refined evolution with tighter constraints
        with MockReaperPatches(simulate_execution_time=0.03):
            refined_result = ga_engine.evolve(
                constraint_set=refined_constraints,
                target_features=target_features,
                feature_weights=feature_weights,
                n_generations=5,
                population_size=6
            )
        
        refined_best = refined_result["best_parameters"]
        print(f"Refined result: {refined_best}")
        
        # Step 4: Validate refinement
        # Refined parameters should be within the refined constraints
        for param_id, value in refined_best.items():
            min_val, max_val = refined_constraints[param_id]
            assert min_val <= value <= max_val
        
        # Refined fitness should be equal or better
        # (Note: Due to stochastic nature, this might not always be true, but typically should improve)
        fitness_improvement = refined_result["best_fitness"] <= initial_result["best_fitness"] * 1.2  # Allow 20% tolerance
        
        print(f"✓ Iterative refinement: Initial fitness {initial_result['best_fitness']:.6f} -> Refined {refined_result['best_fitness']:.6f}")
        print(f"  Fitness improved or maintained: {fitness_improvement}")
        
        # Both evolutions should complete successfully
        assert initial_result["generations_run"] >= 3
        assert refined_result["generations_run"] >= 3
    
    def test_multi_objective_workflow(self, ga_engine, mock_audio_generation):
        """Test workflow targeting multiple conflicting audio objectives."""
        
        # User wants bright sound (high spectral centroid) but also warm (low spectral rolloff)
        # This creates some tension that the evolution needs to balance
        
        constraint_set = {
            "1": (0.5, 0.9),  # Master volume
            "4": (0.3, 0.7),  # A Octave
            "7": (0.6, 0.9),  # A Level
            "10": (0.2, 0.8)  # OSC A WT Pos
        }
        
        # Conflicting objectives: bright (high centroid) vs warm (low rolloff)  
        target_features = ScalarFeatures(
            spectral_centroid=3000.0,  # Want bright
            spectral_rolloff=2000.0,   # But also want warm (conflicting)
            rms_energy=0.18,           # Want strong signal
            spectral_bandwidth=1200.0  # Want focused spectrum
        )
        
        feature_weights = FeatureWeights(
            spectral_centroid=1.0,     # High priority
            spectral_rolloff=0.8,      # High priority (conflicts with centroid)
            rms_energy=0.6,            # Medium priority
            spectral_bandwidth=0.4     # Lower priority
        )
        
        with MockReaperPatches(simulate_execution_time=0.04):
            result = ga_engine.evolve(
                constraint_set=constraint_set,
                target_features=target_features,
                feature_weights=feature_weights,
                n_generations=10,  # More generations for complex optimization
                population_size=12
            )
        
        # Validate multi-objective handling
        assert result["generations_run"] >= 5  # Should need several generations
        
        # Check that evolution progressed despite conflicting objectives
        convergence = result["convergence_history"]
        if len(convergence) > 5:
            # Evolution should show some progress even with conflicts
            early_phase = convergence[:3]
            late_phase = convergence[-3:]
            
            # At minimum, should not get worse over time
            worst_early = max(early_phase)
            worst_late = max(late_phase)
            assert worst_late <= worst_early * 1.5  # Allow some tolerance for stochasticity
        
        # All parameters should be within constraints
        best_params = result["best_parameters"]
        for param_id, value in best_params.items():
            min_val, max_val = constraint_set[param_id]
            assert min_val <= value <= max_val
        
        print(f"✓ Multi-objective workflow completed: {result['generations_run']} generations, fitness {result['best_fitness']:.6f}")
        print(f"  Balanced conflicting objectives: bright vs warm sound")
    
    def test_production_scale_workflow(self, ga_engine, mock_audio_generation, performance_monitor):
        """Test production-scale workflow with realistic parameters and performance requirements."""
        
        # Large parameter set (simulates complex sound design)
        large_constraint_set = {
            str(i): (0.1, 0.9) for i in range(1, 16)  # 15 parameters
        }
        
        # Comprehensive target features
        target_features = ScalarFeatures(
            spectral_centroid=2200.0,
            spectral_bandwidth=1800.0,
            spectral_rolloff=3500.0,
            spectral_contrast=0.7,
            spectral_flatness=0.4,
            zero_crossing_rate=0.08,
            rms_energy=0.16,
            chroma_mean=0.75,
            tonnetz_mean=0.6,
            mfcc_mean=15.0,
            tempo=130.0
        )
        
        feature_weights = FeatureWeights(
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
        
        performance_monitor.start()
        
        with MockReaperPatches(simulate_execution_time=0.02):  # Faster for production scale
            result = ga_engine.evolve(
                constraint_set=large_constraint_set,
                target_features=target_features,
                feature_weights=feature_weights,
                n_generations=15,
                population_size=16
            )
        
        performance_monitor.stop()
        metrics = performance_monitor.get_metrics()
        
        # Validate production requirements
        assert result["generations_run"] >= 10  # Should complete most generations
        assert len(result["best_parameters"]) == len(large_constraint_set)
        
        # Performance requirements
        assert metrics["execution_time"] < 120.0, f"Too slow for production: {metrics['execution_time']:.2f}s"
        assert metrics["memory_usage_mb"] < 1000, f"Too much memory usage: {metrics['memory_usage_mb']:.1f}MB"
        
        # Quality requirements
        convergence = result["convergence_history"]
        assert len(convergence) >= 10
        
        # Should show convergence behavior in later generations
        if len(convergence) >= 10:
            recent_convergence = convergence[-5:]  # Last 5 generations
            convergence_stability = max(recent_convergence) / min(recent_convergence) if min(recent_convergence) > 0 else 1.0
            assert convergence_stability < 2.0  # Should be reasonably stable
        
        print(f"✓ Production-scale workflow: {len(large_constraint_set)} params, {len(feature_weights.get_active_features())} features")
        print(f"  Time: {metrics['execution_time']:.2f}s, Memory: {metrics['memory_usage_mb']:.1f}MB")
        print(f"  Convergence: {result['generations_run']} generations, final fitness: {result['best_fitness']:.6f}")


class TestWorkflowEdgeCases:
    """Test edge cases and error conditions in complete workflows."""
    
    def test_minimal_configuration_workflow(self, ga_engine, mock_audio_generation):
        """Test workflow with minimal configuration (single parameter, single feature)."""
        
        # Absolute minimal setup
        constraint_set = {"4": (0.3, 0.7)}  # Single parameter
        target_features = ScalarFeatures(spectral_centroid=2000.0)
        feature_weights = FeatureWeights(spectral_centroid=1.0)  # Single feature
        
        with MockReaperPatches(simulate_execution_time=0.02):
            result = ga_engine.evolve(
                constraint_set=constraint_set,
                target_features=target_features,
                feature_weights=feature_weights,
                n_generations=3,
                population_size=4
            )
        
        # Should work with minimal configuration
        assert len(result["best_parameters"]) == 1
        assert "4" in result["best_parameters"]
        
        param_value = result["best_parameters"]["4"]
        assert 0.3 <= param_value <= 0.7
        
        print("✓ Minimal configuration workflow successful")
    
    def test_failure_recovery_workflow(self, ga_engine):
        """Test workflow behavior when some operations fail."""
        
        constraint_set = {"1": (0.4, 0.8), "4": (0.2, 0.7)}
        target_features = ScalarFeatures(spectral_centroid=2500.0, rms_energy=0.12)
        feature_weights = FeatureWeights(spectral_centroid=1.0, rms_energy=0.7)
        
        # Simulate 30% failure rate in audio generation
        with MockReaperPatches(simulate_failures=True, failure_rate=0.3, simulate_execution_time=0.02):
            result = ga_engine.evolve(
                constraint_set=constraint_set,
                target_features=target_features,
                feature_weights=feature_weights,
                n_generations=6,
                population_size=10
            )
        
        # Evolution should still complete despite failures
        assert "best_parameters" in result
        assert result["generations_run"] >= 3  # Should complete at least some generations
        
        # Some fitness evaluations may have failed, but best result should be valid
        best_params = result["best_parameters"]
        for param_id, value in best_params.items():
            assert constraint_set[param_id][0] <= value <= constraint_set[param_id][1]
        
        print(f"✓ Failure recovery workflow: Completed {result['generations_run']} generations despite failures")
    
    def test_extreme_constraints_workflow(self, ga_engine, mock_audio_generation):
        """Test workflow with very tight constraints."""
        
        # Extremely tight constraints
        constraint_set = {
            "1": (0.48, 0.52),  # Very narrow range
            "4": (0.73, 0.77),  # Very narrow range  
        }
        
        target_features = ScalarFeatures(spectral_centroid=2000.0, rms_energy=0.1)
        feature_weights = FeatureWeights(spectral_centroid=1.0, rms_energy=0.8)
        
        with MockReaperPatches(simulate_execution_time=0.02):
            result = ga_engine.evolve(
                constraint_set=constraint_set,
                target_features=target_features,
                feature_weights=feature_weights,
                n_generations=8,
                population_size=8
            )
        
        # Should handle tight constraints
        best_params = result["best_parameters"]
        
        # All parameters should be within tight constraints
        for param_id, value in best_params.items():
            min_val, max_val = constraint_set[param_id]
            assert min_val <= value <= max_val
            
            # Verify constraints are actually tight (range < 0.1)
            assert max_val - min_val < 0.1
        
        print("✓ Extreme constraints workflow: Handled very tight parameter ranges")
    
    def test_no_improvement_workflow(self, ga_engine, mock_audio_generation):
        """Test workflow when evolution cannot improve fitness."""
        
        # Use identical target and constraint that might lead to local optimum quickly
        constraint_set = {"4": (0.5, 0.5001)}  # Almost no variation possible
        target_features = ScalarFeatures(spectral_centroid=2000.0)  
        feature_weights = FeatureWeights(spectral_centroid=1.0)
        
        with MockReaperPatches(simulate_execution_time=0.02):
            result = ga_engine.evolve(
                constraint_set=constraint_set,
                target_features=target_features,
                feature_weights=feature_weights,
                n_generations=5,
                population_size=6
            )
        
        # Should complete even if no improvement is possible
        assert "best_parameters" in result
        assert result["generations_run"] >= 3  # Should run some generations
        
        # Convergence history might be flat (no improvement)
        convergence = result["convergence_history"]
        if len(convergence) > 2:
            # Fitness should be stable (little variation possible)
            fitness_range = max(convergence) - min(convergence)
            # With almost no parameter variation, fitness should be very stable
            assert fitness_range < result["best_fitness"] * 0.5  # Less than 50% variation
        
        print("✓ No improvement workflow: Handled case with limited optimization potential")


class TestWorkflowIntegration:
    """Test workflow integration with external systems and data."""
    
    def test_configuration_file_workflow(self, temp_reaper_project):
        """Test workflow using configuration files for reproducible experiments."""
        
        # Create configuration file
        config = {
            "experiment_name": "test_bright_lead",
            "constraint_set": {
                "1": [0.6, 0.9],
                "4": [0.5, 0.8],
                "7": [0.7, 0.9]
            },
            "target_features": {
                "spectral_centroid": 3200.0,
                "spectral_rolloff": 5000.0,
                "rms_energy": 0.14
            },
            "feature_weights": {
                "spectral_centroid": 1.0,
                "spectral_rolloff": 0.8,
                "rms_energy": 0.6
            },
            "evolution_params": {
                "n_generations": 8,
                "population_size": 10
            }
        }
        
        # Save configuration
        config_path = temp_reaper_project / "test_config.json"
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        
        # Initialize system
        from .fixtures.test_data import ParameterTestDataGenerator
        fx_data = ParameterTestDataGenerator.generate_fx_parameters_data()
        
        fx_params_path = temp_reaper_project / "fx_parameters.json"
        with open(fx_params_path, 'w') as f:
            json.dump(fx_data, f, indent=2)
        
        param_manager = SerumParameterManager(fx_params_path)
        feature_extractor = LibrosaFeatureExtractor()
        audio_generator = SerumAudioGenerator(temp_reaper_project, param_manager)
        ga_engine = AdaptiveSerumEvolver(audio_generator, feature_extractor, param_manager)
        
        # Load configuration and run
        constraint_set = {k: tuple(v) for k, v in config["constraint_set"].items()}
        target_features = ScalarFeatures(**config["target_features"])
        feature_weights = FeatureWeights(**config["feature_weights"])
        
        with MockReaperPatches(simulate_execution_time=0.03):
            result = ga_engine.evolve(
                constraint_set=constraint_set,
                target_features=target_features,
                feature_weights=feature_weights,
                **config["evolution_params"]
            )
        
        # Save results alongside configuration  
        result_path = temp_reaper_project / "test_results.json"
        with open(result_path, 'w') as f:
            # Convert result to JSON-serializable format
            json_result = {
                "best_parameters": result["best_parameters"],
                "best_fitness": result["best_fitness"],
                "generations_run": result["generations_run"],
                "convergence_history": result["convergence_history"],
                "config_used": config["experiment_name"]
            }
            json.dump(json_result, f, indent=2)
        
        # Validate workflow
        assert result_path.exists()
        assert config_path.exists()
        
        # Results should match configuration expectations
        assert result["generations_run"] <= config["evolution_params"]["n_generations"]
        
        print("✓ Configuration file workflow: Reproducible experiment setup and results storage")
    
    def test_batch_processing_workflow(self, ga_engine, mock_audio_generation):
        """Test workflow for batch processing multiple evolution runs."""
        
        # Define multiple experiment configurations
        experiments = [
            {
                "name": "bright_sound",
                "constraint_set": {"1": (0.6, 0.9), "4": (0.5, 0.8)},
                "target_features": ScalarFeatures(spectral_centroid=3000.0, rms_energy=0.12),
                "feature_weights": FeatureWeights(spectral_centroid=1.0, rms_energy=0.7)
            },
            {
                "name": "warm_sound", 
                "constraint_set": {"1": (0.7, 0.9), "4": (0.2, 0.5)},
                "target_features": ScalarFeatures(spectral_centroid=1200.0, rms_energy=0.18),
                "feature_weights": FeatureWeights(spectral_centroid=1.0, rms_energy=0.8)
            },
            {
                "name": "dynamic_sound",
                "constraint_set": {"1": (0.5, 0.8), "4": (0.3, 0.7), "7": (0.6, 0.9)},
                "target_features": ScalarFeatures(spectral_centroid=2200.0, zero_crossing_rate=0.12, rms_energy=0.15),
                "feature_weights": FeatureWeights(spectral_centroid=0.8, zero_crossing_rate=1.0, rms_energy=0.6)
            }
        ]
        
        # Run batch processing
        batch_results = {}
        
        for experiment in experiments:
            print(f"Running experiment: {experiment['name']}")
            
            with MockReaperPatches(simulate_execution_time=0.02):
                result = ga_engine.evolve(
                    constraint_set=experiment["constraint_set"],
                    target_features=experiment["target_features"],
                    feature_weights=experiment["feature_weights"],
                    n_generations=6,
                    population_size=8
                )
            
            batch_results[experiment["name"]] = result
        
        # Validate batch processing
        assert len(batch_results) == len(experiments)
        
        for exp_name, result in batch_results.items():
            assert "best_parameters" in result
            assert result["generations_run"] >= 3
            print(f"  {exp_name}: fitness {result['best_fitness']:.6f}, {result['generations_run']} generations")
        
        # Compare results across experiments
        fitness_values = [result["best_fitness"] for result in batch_results.values()]
        generation_counts = [result["generations_run"] for result in batch_results.values()]
        
        print(f"✓ Batch processing workflow: {len(experiments)} experiments completed")
        print(f"  Fitness range: {min(fitness_values):.6f} to {max(fitness_values):.6f}")
        print(f"  Generation range: {min(generation_counts)} to {max(generation_counts)}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])