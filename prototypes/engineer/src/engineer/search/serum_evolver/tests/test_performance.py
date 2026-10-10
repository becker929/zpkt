"""
Performance benchmarks and stress tests for SerumEvolver system.

This test suite validates system performance under various load conditions and
ensures the system meets performance requirements for production usage.
"""

import pytest
import time
import psutil
import gc
import threading
from pathlib import Path
from typing import Dict, Any, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch
import numpy as np

from serum_evolver.interfaces import SerumParameters, ParameterConstraintSet, ScalarFeatures, FeatureWeights
from serum_evolver.parameter_manager import SerumParameterManager
from serum_evolver.feature_extractor import LibrosaFeatureExtractor
from serum_evolver.audio_generator import SerumAudioGenerator
from serum_evolver.ga_engine import AdaptiveSerumEvolver

from .fixtures.test_data import BenchmarkDataGenerator, ParameterTestDataGenerator, FeatureTestDataGenerator
from .fixtures.mock_reaper import MockReaperPatches, create_performance_audio_file


class TestPerformanceBenchmarks:
    """Performance benchmarks for system components and integrated workflows."""
    
    def test_evolution_speed_benchmark(self, ga_engine, performance_monitor, mock_audio_generation):
        """Benchmark evolution speed across different problem sizes."""
        
        benchmark_cases = BenchmarkDataGenerator.generate_performance_test_cases()
        results = {}
        
        for case_name, case_config in benchmark_cases.items():
            print(f"\nBenchmarking {case_name}...")
            
            # Setup
            constraint_set = case_config["constraint_set"]
            target_features = ScalarFeatures(spectral_centroid=2200.0, rms_energy=0.12)
            feature_weights = FeatureWeights(spectral_centroid=1.0, rms_energy=0.8)
            
            # Run benchmark
            performance_monitor.start()
            
            with MockReaperPatches(simulate_execution_time=0.01):  # Fast mock execution
                result = ga_engine.evolve(
                    constraint_set=constraint_set,
                    target_features=target_features,
                    feature_weights=feature_weights,
                    n_generations=case_config["n_generations"],
                    population_size=case_config["population_size"]
                )
            
            performance_monitor.stop()
            metrics = performance_monitor.get_metrics()
            
            # Validate performance requirements
            assert metrics["execution_time"] <= case_config["expected_max_time"], \
                f"{case_name}: Too slow {metrics['execution_time']:.2f}s > {case_config['expected_max_time']}s"
            
            assert metrics["memory_usage_mb"] <= case_config["expected_max_memory_mb"], \
                f"{case_name}: Too much memory {metrics['memory_usage_mb']:.1f}MB > {case_config['expected_max_memory_mb']}MB"
            
            # Store results
            results[case_name] = {
                "execution_time": metrics["execution_time"],
                "memory_usage_mb": metrics["memory_usage_mb"],
                "generations_run": result["generations_run"],
                "population_size": case_config["population_size"],
                "parameter_count": len(constraint_set),
                "fitness": result["best_fitness"]
            }
            
            print(f"  ✓ {case_name}: {metrics['execution_time']:.2f}s, {metrics['memory_usage_mb']:.1f}MB")
        
        # Performance scaling analysis
        print("\n📊 Performance Scaling Analysis:")
        for case_name, metrics in results.items():
            params_per_second = (metrics["parameter_count"] * metrics["population_size"] * metrics["generations_run"]) / metrics["execution_time"]
            print(f"  {case_name}: {params_per_second:.1f} parameter evaluations/second")
        
        print("✓ Evolution speed benchmarks completed successfully")
    
    def test_memory_usage_patterns(self, ga_engine, mock_audio_generation):
        """Test memory usage patterns and detect memory leaks."""
        import gc
        
        # Get baseline memory
        gc.collect()
        process = psutil.Process()
        baseline_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        constraint_set = {"1": (0.3, 0.8), "4": (0.2, 0.7), "7": (0.5, 0.9)}
        target_features = ScalarFeatures(spectral_centroid=2000.0, rms_energy=0.15)
        feature_weights = FeatureWeights(spectral_centroid=1.0, rms_energy=0.8)
        
        memory_measurements = [baseline_memory]
        
        # Run multiple evolution cycles
        for cycle in range(5):
            with MockReaperPatches(simulate_execution_time=0.01):
                result = ga_engine.evolve(
                    constraint_set=constraint_set,
                    target_features=target_features,
                    feature_weights=feature_weights,
                    n_generations=5,
                    population_size=8
                )
            
            # Force cleanup and measure memory
            del result
            gc.collect()
            
            current_memory = process.memory_info().rss / 1024 / 1024
            memory_measurements.append(current_memory)
            
            print(f"  Cycle {cycle+1}: {current_memory:.1f}MB")
        
        # Analyze memory growth
        memory_growth = memory_measurements[-1] - baseline_memory
        max_growth = max(memory_measurements) - baseline_memory
        
        # Memory growth should be reasonable (< 50MB total, < 100MB peak)
        assert memory_growth < 50, f"Excessive memory growth: {memory_growth:.1f}MB"
        assert max_growth < 100, f"Excessive peak memory: {max_growth:.1f}MB"
        
        # Check for memory leaks (steady growth)
        if len(memory_measurements) >= 5:
            recent_trend = np.polyfit(range(len(memory_measurements[-3:])), memory_measurements[-3:], 1)[0]
            assert recent_trend < 5.0, f"Potential memory leak detected: {recent_trend:.2f}MB/cycle"
        
        print(f"✓ Memory usage: Growth {memory_growth:.1f}MB, Peak {max_growth:.1f}MB")
    
    def test_parameter_validation_performance(self, parameter_manager, performance_monitor):
        """Benchmark parameter validation performance."""
        
        # Generate large parameter sets
        test_cases = [
            ("small", 10),
            ("medium", 50), 
            ("large", 100),
            ("xlarge", 500)
        ]
        
        for case_name, param_count in test_cases:
            print(f"\nTesting {case_name} parameter set ({param_count} parameters)...")
            
            # Generate test data
            fx_data = ParameterTestDataGenerator.generate_fx_parameters_data(param_count)
            
            # Save and reload parameter manager with large dataset
            import tempfile, json
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(fx_data, f)
                temp_path = Path(f.name)
            
            try:
                # Create parameter manager with large dataset
                large_param_manager = SerumParameterManager(temp_path)
                
                # Benchmark parameter validation
                test_values = [0.0, 0.25, 0.5, 0.75, 1.0]
                param_ids = large_param_manager.get_all_parameter_ids()[:100]  # Test first 100
                
                performance_monitor.start()
                
                for param_id in param_ids:
                    for value in test_values:
                        large_param_manager.validate_parameter_value(param_id, value)
                
                performance_monitor.stop()
                metrics = performance_monitor.get_metrics()
                
                # Calculate performance metrics
                total_validations = len(param_ids) * len(test_values)
                validations_per_second = total_validations / metrics["execution_time"]
                
                # Performance requirement: > 10000 validations/second
                assert validations_per_second > 10000, \
                    f"Parameter validation too slow: {validations_per_second:.1f}/sec"
                
                print(f"  ✓ {case_name}: {validations_per_second:.0f} validations/second")
                
            finally:
                temp_path.unlink()
    
    def test_feature_extraction_performance(self, feature_extractor, performance_monitor):
        """Benchmark feature extraction performance with different audio complexities."""
        
        import tempfile
        
        test_cases = [
            ("simple", "simple", 2.0),
            ("medium", "medium", 5.0),
            ("complex", "high", 10.0)
        ]
        
        for case_name, complexity, duration in test_cases:
            print(f"\nTesting {case_name} feature extraction...")
            
            # Create test audio file
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                audio_path = create_performance_audio_file(
                    Path(temp_file.name), 
                    duration=duration,
                    complexity=complexity
                )
            
            try:
                # Test different feature weight configurations
                feature_configs = [
                    FeatureWeights(spectral_centroid=1.0),  # Single feature
                    FeatureWeights(spectral_centroid=1.0, rms_energy=0.8, spectral_bandwidth=0.6),  # Multiple features
                    FeatureWeights(**{attr: 1.0 for attr in FeatureWeights.__annotations__ if attr != 'get_active_features'})  # All features
                ]
                
                for i, weights in enumerate(feature_configs):
                    active_count = len(weights.get_active_features())
                    
                    performance_monitor.start()
                    features = feature_extractor.extract_scalar_features(audio_path, weights)
                    performance_monitor.stop()
                    
                    metrics = performance_monitor.get_metrics()
                    
                    # Performance requirement: < 5 seconds per extraction for complex audio
                    max_time = 5.0 if complexity == "high" else 2.0
                    assert metrics["execution_time"] < max_time, \
                        f"Feature extraction too slow: {metrics['execution_time']:.2f}s > {max_time}s"
                    
                    print(f"    Config {i+1} ({active_count} features): {metrics['execution_time']:.3f}s")
            
            finally:
                audio_path.unlink()
        
        print("✓ Feature extraction performance benchmarks completed")


class TestStressTesting:
    """Stress tests for system limits and robustness."""
    
    def test_large_population_stress(self, ga_engine, performance_monitor, mock_audio_generation):
        """Stress test with large population sizes."""
        
        # Large population stress test
        constraint_set = {str(i): (0.0, 1.0) for i in range(1, 11)}  # 10 parameters
        target_features = ScalarFeatures(
            spectral_centroid=2500.0,
            spectral_bandwidth=1800.0,
            rms_energy=0.15
        )
        feature_weights = FeatureWeights(
            spectral_centroid=1.0,
            spectral_bandwidth=0.8,
            rms_energy=0.6
        )
        
        # Test increasing population sizes
        population_sizes = [8, 16, 32, 64]
        results = {}
        
        for pop_size in population_sizes:
            print(f"\nStress testing population size: {pop_size}")
            
            performance_monitor.start()
            
            with MockReaperPatches(simulate_execution_time=0.005):  # Very fast mock
                result = ga_engine.evolve(
                    constraint_set=constraint_set,
                    target_features=target_features,
                    feature_weights=feature_weights,
                    n_generations=5,
                    population_size=pop_size
                )
            
            performance_monitor.stop()
            metrics = performance_monitor.get_metrics()
            
            results[pop_size] = metrics
            
            # Validate completion
            assert result["generations_run"] >= 3
            assert len(result["best_parameters"]) == len(constraint_set)
            
            # Memory usage should scale reasonably
            expected_max_memory = pop_size * 5  # ~5MB per individual (generous estimate)
            assert metrics["memory_usage_mb"] < expected_max_memory, \
                f"Memory usage too high: {metrics['memory_usage_mb']:.1f}MB > {expected_max_memory}MB"
            
            print(f"  ✓ Pop {pop_size}: {metrics['execution_time']:.2f}s, {metrics['memory_usage_mb']:.1f}MB")
        
        # Analyze scaling behavior
        print("\n📊 Population Scaling Analysis:")
        for pop_size in population_sizes:
            metrics = results[pop_size]
            evaluations_per_second = (pop_size * 5) / metrics["execution_time"]  # 5 generations
            print(f"  Pop {pop_size}: {evaluations_per_second:.1f} evaluations/second")
    
    def test_long_evolution_stress(self, ga_engine, performance_monitor, mock_audio_generation):
        """Stress test with long evolution runs."""
        
        constraint_set = {"1": (0.2, 0.8), "4": (0.3, 0.7), "7": (0.4, 0.9)}
        target_features = ScalarFeatures(spectral_centroid=2200.0, rms_energy=0.12)
        feature_weights = FeatureWeights(spectral_centroid=1.0, rms_energy=0.8)
        
        # Long evolution run
        performance_monitor.start()
        
        with MockReaperPatches(simulate_execution_time=0.002):  # Very fast for long test
            result = ga_engine.evolve(
                constraint_set=constraint_set,
                target_features=target_features,
                feature_weights=feature_weights,
                n_generations=50,  # Long evolution
                population_size=12
            )
        
        performance_monitor.stop()
        metrics = performance_monitor.get_metrics()
        
        # Validate long evolution
        assert result["generations_run"] >= 40  # Should complete most generations
        
        # Check convergence behavior
        convergence = result["convergence_history"]
        assert len(convergence) >= 40
        
        # Should show convergence over long run
        early_average = np.mean(convergence[:10])
        late_average = np.mean(convergence[-10:])
        
        # Fitness should improve or stabilize (not get worse)
        assert late_average <= early_average * 1.1  # Allow 10% tolerance
        
        # Memory should remain stable over long runs
        assert metrics["memory_usage_mb"] < 300, f"Memory usage too high in long run: {metrics['memory_usage_mb']:.1f}MB"
        
        print(f"✓ Long evolution stress test: {result['generations_run']} generations in {metrics['execution_time']:.2f}s")
        print(f"  Convergence: {early_average:.6f} -> {late_average:.6f}")
    
    def test_concurrent_evolution_stress(self, ga_engine, mock_audio_generation, concurrency_tester):
        """Stress test with multiple concurrent evolution runs."""
        
        def run_concurrent_evolution(evolution_id: int) -> Dict[str, Any]:
            """Run a single evolution for concurrency testing."""
            constraint_set = {
                "1": (0.2 + evolution_id * 0.1, 0.8),
                "4": (0.1, 0.7 + evolution_id * 0.05)  # Slightly different constraints
            }
            target_features = ScalarFeatures(
                spectral_centroid=2000.0 + evolution_id * 100,
                rms_energy=0.10 + evolution_id * 0.01
            )
            feature_weights = FeatureWeights(spectral_centroid=1.0, rms_energy=0.8)
            
            with MockReaperPatches(simulate_execution_time=0.01):
                result = ga_engine.evolve(
                    constraint_set=constraint_set,
                    target_features=target_features,
                    feature_weights=feature_weights,
                    n_generations=8,
                    population_size=6
                )
            
            return {
                "evolution_id": evolution_id,
                "best_fitness": result["best_fitness"],
                "generations_run": result["generations_run"],
                "parameter_count": len(result["best_parameters"])
            }
        
        # Run multiple concurrent evolutions
        num_concurrent = 8
        evolution_args = [(i,) for i in range(num_concurrent)]
        
        start_time = time.time()
        concurrency_tester.run_concurrent(run_concurrent_evolution, evolution_args, max_workers=4)
        end_time = time.time()
        
        concurrency_tester.assert_all_successful(num_concurrent)
        results = concurrency_tester.get_results()
        
        # Validate concurrent execution
        assert len(results) == num_concurrent
        
        # All evolutions should complete successfully
        for result in results:
            assert result["generations_run"] >= 5
            assert result["parameter_count"] >= 2
            assert not np.isnan(result["best_fitness"])
        
        # Concurrent execution should be faster than sequential
        total_time = end_time - start_time
        estimated_sequential_time = num_concurrent * 3.0  # ~3s per evolution estimate
        
        print(f"✓ Concurrent evolution stress test: {num_concurrent} evolutions in {total_time:.2f}s")
        print(f"  Speedup vs sequential: {estimated_sequential_time/total_time:.1f}x")
        
        # Check result diversity (different random seeds should produce different results)
        fitness_values = [r["best_fitness"] for r in results]
        fitness_std = np.std(fitness_values)
        assert fitness_std > 0.01, "Results too similar - potential thread safety issue"
    
    def test_memory_pressure_stress(self, ga_engine, mock_audio_generation):
        """Stress test under high memory pressure."""
        
        # Allocate large memory arrays to create memory pressure
        memory_pressure_data = []
        try:
            # Allocate ~500MB of memory
            for _ in range(5):
                large_array = BenchmarkDataGenerator.generate_memory_stress_data(100.0)  # 100MB each
                memory_pressure_data.append(large_array)
            
            # Run evolution under memory pressure
            constraint_set = {str(i): (0.1, 0.9) for i in range(1, 21)}  # 20 parameters
            target_features = ScalarFeatures(
                spectral_centroid=2200.0,
                spectral_bandwidth=1800.0, 
                rms_energy=0.15
            )
            feature_weights = FeatureWeights(
                spectral_centroid=1.0,
                spectral_bandwidth=0.8,
                rms_energy=0.6
            )
            
            with MockReaperPatches(simulate_execution_time=0.01):
                result = ga_engine.evolve(
                    constraint_set=constraint_set,
                    target_features=target_features,
                    feature_weights=feature_weights,
                    n_generations=10,
                    population_size=12
                )
            
            # Should complete successfully despite memory pressure
            assert result["generations_run"] >= 8
            assert len(result["best_parameters"]) == len(constraint_set)
            
            print(f"✓ Memory pressure stress test: Completed {result['generations_run']} generations under ~500MB memory pressure")
            
        finally:
            # Cleanup memory pressure data
            del memory_pressure_data
            gc.collect()
    
    def test_failure_cascade_stress(self, ga_engine):
        """Stress test with cascading failures."""
        
        constraint_set = {"1": (0.3, 0.7), "4": (0.2, 0.8), "7": (0.5, 0.9)}
        target_features = ScalarFeatures(spectral_centroid=2000.0, rms_energy=0.12)
        feature_weights = FeatureWeights(spectral_centroid=1.0, rms_energy=0.8)
        
        # High failure rate to stress error handling
        with MockReaperPatches(simulate_failures=True, failure_rate=0.7, simulate_execution_time=0.01):
            result = ga_engine.evolve(
                constraint_set=constraint_set,
                target_features=target_features,
                feature_weights=feature_weights,
                n_generations=10,
                population_size=16  # Large population to increase failure chances
            )
        
        # Should still complete despite high failure rate
        assert "best_parameters" in result
        assert result["generations_run"] >= 3  # Should complete some generations
        
        # Best result should still be valid despite failures
        best_params = result["best_parameters"]
        for param_id, value in best_params.items():
            min_val, max_val = constraint_set[param_id]
            assert min_val <= value <= max_val
        
        print(f"✓ Failure cascade stress test: Completed {result['generations_run']} generations with 70% failure rate")


class TestScalabilityAnalysis:
    """Analyze system scalability characteristics."""
    
    def test_parameter_count_scalability(self, ga_engine, performance_monitor, mock_audio_generation):
        """Analyze how performance scales with parameter count."""
        
        parameter_counts = [2, 5, 10, 20, 50]
        scaling_results = {}
        
        for param_count in parameter_counts:
            print(f"\nTesting scalability with {param_count} parameters...")
            
            # Generate constraint set
            constraint_set = {str(i): (0.1, 0.9) for i in range(1, param_count + 1)}
            
            target_features = ScalarFeatures(spectral_centroid=2200.0, rms_energy=0.12)
            feature_weights = FeatureWeights(spectral_centroid=1.0, rms_energy=0.8)
            
            performance_monitor.start()
            
            with MockReaperPatches(simulate_execution_time=0.005):
                result = ga_engine.evolve(
                    constraint_set=constraint_set,
                    target_features=target_features,
                    feature_weights=feature_weights,
                    n_generations=8,
                    population_size=10
                )
            
            performance_monitor.stop()
            metrics = performance_monitor.get_metrics()
            
            scaling_results[param_count] = {
                "execution_time": metrics["execution_time"],
                "memory_usage_mb": metrics["memory_usage_mb"],
                "generations_run": result["generations_run"]
            }
            
            print(f"  {param_count} params: {metrics['execution_time']:.2f}s, {metrics['memory_usage_mb']:.1f}MB")
        
        # Analyze scaling behavior
        print("\n📊 Parameter Scalability Analysis:")
        
        param_counts = list(scaling_results.keys())
        execution_times = [scaling_results[pc]["execution_time"] for pc in param_counts]
        memory_usages = [scaling_results[pc]["memory_usage_mb"] for pc in param_counts]
        
        # Calculate scaling factors
        for i in range(1, len(param_counts)):
            param_ratio = param_counts[i] / param_counts[i-1]
            time_ratio = execution_times[i] / execution_times[i-1]
            memory_ratio = memory_usages[i] / memory_usages[i-1]
            
            print(f"  {param_counts[i-1]} -> {param_counts[i]} params: {time_ratio:.2f}x time, {memory_ratio:.2f}x memory")
        
        # Performance should scale reasonably (not exponentially)
        max_time_growth = max(execution_times[i] / execution_times[i-1] for i in range(1, len(execution_times)))
        assert max_time_growth < 5.0, f"Execution time scaling too poor: {max_time_growth:.2f}x"
        
        print("✓ Parameter scalability analysis completed")
    
    def test_generation_count_scalability(self, ga_engine, performance_monitor, mock_audio_generation):
        """Analyze how performance scales with generation count."""
        
        generation_counts = [5, 10, 20, 50]
        constraint_set = {"1": (0.2, 0.8), "4": (0.3, 0.7), "7": (0.4, 0.9)}
        target_features = ScalarFeatures(spectral_centroid=2200.0, rms_energy=0.12)
        feature_weights = FeatureWeights(spectral_centroid=1.0, rms_energy=0.8)
        
        scaling_results = {}
        
        for gen_count in generation_counts:
            print(f"\nTesting scalability with {gen_count} generations...")
            
            performance_monitor.start()
            
            with MockReaperPatches(simulate_execution_time=0.003):
                result = ga_engine.evolve(
                    constraint_set=constraint_set,
                    target_features=target_features,
                    feature_weights=feature_weights,
                    n_generations=gen_count,
                    population_size=8
                )
            
            performance_monitor.stop()
            metrics = performance_monitor.get_metrics()
            
            scaling_results[gen_count] = {
                "execution_time": metrics["execution_time"],
                "memory_usage_mb": metrics["memory_usage_mb"],
                "actual_generations": result["generations_run"]
            }
            
            print(f"  {gen_count} gens: {metrics['execution_time']:.2f}s, {metrics['memory_usage_mb']:.1f}MB")
        
        # Generation scaling should be approximately linear
        print("\n📊 Generation Scalability Analysis:")
        
        gen_counts = list(scaling_results.keys())
        execution_times = [scaling_results[gc]["execution_time"] for gc in gen_counts]
        
        for i in range(1, len(gen_counts)):
            gen_ratio = gen_counts[i] / gen_counts[i-1]
            time_ratio = execution_times[i] / execution_times[i-1]
            
            # Time scaling should be approximately linear with generations
            assert 0.8 < time_ratio / gen_ratio < 1.5, \
                f"Generation scaling not linear: {time_ratio:.2f}x time for {gen_ratio:.2f}x generations"
            
            print(f"  {gen_counts[i-1]} -> {gen_counts[i]} gens: {time_ratio:.2f}x time (expected ~{gen_ratio:.2f}x)")
        
        print("✓ Generation scalability analysis completed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])  # -s to show print statements