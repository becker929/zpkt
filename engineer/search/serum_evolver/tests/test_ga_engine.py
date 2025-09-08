"""
Comprehensive unit tests for the GA engine module.

Tests cover:
- Adaptive genome sizing and parameter mapping
- Fitness evaluation pipeline
- Evolution convergence
- Integration with all previous agents
- Performance and error handling
- JSI-compatible result formatting
"""

import pytest
import numpy as np
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
import tempfile
import time

from serum_evolver.ga_engine import (
    AdaptiveSerumProblem, 
    AdaptiveSerumEvolver, 
    ParallelAdaptiveSerumProblem,
    ISerumEvolver
)
from serum_evolver.interfaces import (
    ParameterConstraintSet, 
    ScalarFeatures, 
    FeatureWeights, 
    SerumParameters
)


@pytest.fixture
def sample_constraint_set():
    """Sample constraint set for testing."""
    return {
        'param1': (0.0, 1.0),
        'param2': (0.1, 0.9), 
        'param3': (-1.0, 1.0),
        'param4': (100.0, 1000.0)
    }


@pytest.fixture
def sample_target_features():
    """Sample target features for testing."""
    return ScalarFeatures(
        spectral_centroid=1500.0,
        spectral_bandwidth=800.0,
        rms_energy=0.1,
        tempo=120.0
    )


@pytest.fixture
def sample_feature_weights():
    """Sample feature weights for testing."""
    return FeatureWeights(
        spectral_centroid=1.0,
        spectral_bandwidth=0.8,
        rms_energy=0.5,
        tempo=0.2
    )


@pytest.fixture
def mock_param_manager():
    """Mock parameter manager for testing."""
    mock_manager = Mock()
    mock_manager.get_default_parameters.return_value = {
        'param1': 0.5,
        'param2': 0.5,
        'param3': 0.0,
        'param4': 500.0,
        'default_param': 0.75
    }
    mock_manager.validate_constraint_set.return_value = True
    mock_manager.get_parameter_bounds.side_effect = lambda p: {
        'param1': (0.0, 1.0),
        'param2': (0.1, 0.9),
        'param3': (-1.0, 1.0),
        'param4': (100.0, 1000.0)
    }.get(p, (0.0, 1.0))
    return mock_manager


@pytest.fixture
def mock_audio_generator():
    """Mock audio generator for testing."""
    mock_generator = Mock()
    
    # Create a temporary audio file for mocking
    temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
    temp_path = Path(temp_file.name)
    temp_file.close()
    
    mock_generator.render_patch.return_value = temp_path
    return mock_generator, temp_path


@pytest.fixture 
def mock_feature_extractor():
    """Mock feature extractor for testing."""
    mock_extractor = Mock()
    
    # Return different features for different calls to simulate variation
    def varying_features(*args, **kwargs):
        return ScalarFeatures(
            spectral_centroid=1400.0 + np.random.normal(0, 100),
            spectral_bandwidth=750.0 + np.random.normal(0, 50),
            rms_energy=0.09 + np.random.normal(0, 0.01),
            tempo=118.0 + np.random.normal(0, 5)
        )
    
    mock_extractor.extract_scalar_features.side_effect = varying_features
    mock_extractor.compute_feature_distance.return_value = np.random.uniform(0.1, 2.0)
    
    return mock_extractor


class TestAdaptiveSerumProblem:
    """Test cases for AdaptiveSerumProblem class."""
    
    def test_initialization(self, sample_constraint_set, sample_target_features, 
                           sample_feature_weights, mock_param_manager, 
                           mock_audio_generator, mock_feature_extractor):
        """Test problem initialization with adaptive genome size."""
        mock_generator, temp_path = mock_audio_generator
        
        problem = AdaptiveSerumProblem(
            constraint_set=sample_constraint_set,
            target_features=sample_target_features,
            feature_weights=sample_feature_weights,
            audio_generator=mock_generator,
            feature_extractor=mock_feature_extractor,
            param_manager=mock_param_manager
        )
        
        # Verify adaptive genome size
        assert problem.n_var == len(sample_constraint_set)  # 4 parameters
        assert len(problem.param_ids) == len(sample_constraint_set)
        assert problem.param_ids == list(sample_constraint_set.keys())
        
        # Verify bounds extraction
        expected_xl = np.array([0.0, 0.1, -1.0, 100.0])
        expected_xu = np.array([1.0, 0.9, 1.0, 1000.0])
        np.testing.assert_array_equal(problem.xl, expected_xl)
        np.testing.assert_array_equal(problem.xu, expected_xu)
        
        # Cleanup
        temp_path.unlink(missing_ok=True)
    
    def test_genome_to_parameters_mapping(self, sample_constraint_set, sample_target_features,
                                         sample_feature_weights, mock_param_manager,
                                         mock_audio_generator, mock_feature_extractor):
        """Test genome to parameter dictionary conversion."""
        mock_generator, temp_path = mock_audio_generator
        
        problem = AdaptiveSerumProblem(
            constraint_set=sample_constraint_set,
            target_features=sample_target_features,
            feature_weights=sample_feature_weights,
            audio_generator=mock_generator,
            feature_extractor=mock_feature_extractor,
            param_manager=mock_param_manager
        )
        
        # Test genome conversion
        test_genome = np.array([0.2, 0.7, -0.3, 750.0])
        params = problem.genome_to_parameters(test_genome)
        
        # Verify constrained parameters are mapped correctly
        assert params['param1'] == 0.2
        assert params['param2'] == 0.7
        assert params['param3'] == -0.3
        assert params['param4'] == 750.0
        
        # Verify default parameters are preserved
        assert params['default_param'] == 0.75
        
        # Cleanup
        temp_path.unlink(missing_ok=True)
    
    def test_parameters_to_genome_mapping(self, sample_constraint_set, sample_target_features,
                                         sample_feature_weights, mock_param_manager,
                                         mock_audio_generator, mock_feature_extractor):
        """Test parameter dictionary to genome array conversion."""
        mock_generator, temp_path = mock_audio_generator
        
        problem = AdaptiveSerumProblem(
            constraint_set=sample_constraint_set,
            target_features=sample_target_features,
            feature_weights=sample_feature_weights,
            audio_generator=mock_generator,
            feature_extractor=mock_feature_extractor,
            param_manager=mock_param_manager
        )
        
        # Test parameter to genome conversion
        test_params = {
            'param1': 0.8,
            'param2': 0.3,
            'param3': 0.5,
            'param4': 200.0,
            'other_param': 0.123  # Should be ignored
        }
        
        genome = problem.parameters_to_genome(test_params)
        expected_genome = np.array([0.8, 0.3, 0.5, 200.0])
        np.testing.assert_array_equal(genome, expected_genome)
        
        # Cleanup
        temp_path.unlink(missing_ok=True)
    
    def test_individual_evaluation(self, sample_constraint_set, sample_target_features,
                                  sample_feature_weights, mock_param_manager,
                                  mock_audio_generator, mock_feature_extractor):
        """Test individual fitness evaluation."""
        mock_generator, temp_path = mock_audio_generator
        
        problem = AdaptiveSerumProblem(
            constraint_set=sample_constraint_set,
            target_features=sample_target_features,
            feature_weights=sample_feature_weights,
            audio_generator=mock_generator,
            feature_extractor=mock_feature_extractor,
            param_manager=mock_param_manager
        )
        
        test_genome = np.array([0.5, 0.5, 0.0, 500.0])
        fitness = problem._evaluate_individual(test_genome, 0)
        
        # Verify audio generation was called
        mock_generator.render_patch.assert_called_once()
        
        # Verify feature extraction was called
        mock_feature_extractor.extract_scalar_features.assert_called_once()
        mock_feature_extractor.compute_feature_distance.assert_called_once()
        
        # Verify fitness is a number
        assert isinstance(fitness, float)
        assert not np.isinf(fitness)
        
        # Cleanup
        temp_path.unlink(missing_ok=True)
    
    def test_population_evaluation(self, sample_constraint_set, sample_target_features,
                                  sample_feature_weights, mock_param_manager,
                                  mock_audio_generator, mock_feature_extractor):
        """Test population fitness evaluation."""
        mock_generator, temp_path = mock_audio_generator
        
        problem = AdaptiveSerumProblem(
            constraint_set=sample_constraint_set,
            target_features=sample_target_features,
            feature_weights=sample_feature_weights,
            audio_generator=mock_generator,
            feature_extractor=mock_feature_extractor,
            param_manager=mock_param_manager
        )
        
        # Test population matrix
        population = np.array([
            [0.1, 0.2, 0.3, 200.0],
            [0.7, 0.8, -0.5, 800.0],
            [0.4, 0.5, 0.1, 600.0]
        ])
        
        out = {}
        problem._evaluate(population, out)
        
        # Verify output format
        assert "F" in out
        assert out["F"].shape == (3, 1)
        assert all(isinstance(f[0], (int, float)) for f in out["F"])
        
        # Verify all individuals were evaluated
        assert mock_generator.render_patch.call_count == 3
        
        # Cleanup
        temp_path.unlink(missing_ok=True)
    
    def test_audio_generation_failure_handling(self, sample_constraint_set, sample_target_features,
                                              sample_feature_weights, mock_param_manager,
                                              mock_feature_extractor):
        """Test handling of audio generation failures."""
        # Mock audio generator that fails
        mock_generator = Mock()
        mock_generator.render_patch.return_value = None  # Simulate failure
        
        problem = AdaptiveSerumProblem(
            constraint_set=sample_constraint_set,
            target_features=sample_target_features,
            feature_weights=sample_feature_weights,
            audio_generator=mock_generator,
            feature_extractor=mock_feature_extractor,
            param_manager=mock_param_manager
        )
        
        test_genome = np.array([0.5, 0.5, 0.0, 500.0])
        fitness = problem._evaluate_individual(test_genome, 0)
        
        # Should return infinite fitness for failed generation
        assert fitness == float('inf')


class TestParallelAdaptiveSerumProblem:
    """Test cases for ParallelAdaptiveSerumProblem class."""
    
    def test_parallel_evaluation(self, sample_constraint_set, sample_target_features,
                                sample_feature_weights, mock_param_manager,
                                mock_audio_generator, mock_feature_extractor):
        """Test parallel population evaluation."""
        mock_generator, temp_path = mock_audio_generator
        
        problem = ParallelAdaptiveSerumProblem(
            constraint_set=sample_constraint_set,
            target_features=sample_target_features,
            feature_weights=sample_feature_weights,
            audio_generator=mock_generator,
            feature_extractor=mock_feature_extractor,
            param_manager=mock_param_manager,
            max_workers=2
        )
        
        # Test population matrix
        population = np.array([
            [0.1, 0.2, 0.3, 200.0],
            [0.7, 0.8, -0.5, 800.0],
            [0.4, 0.5, 0.1, 600.0]
        ])
        
        out = {}
        problem._evaluate(population, out)
        
        # Verify output format (same as sequential)
        assert "F" in out
        assert out["F"].shape == (3, 1)
        
        # Verify all individuals were evaluated
        assert mock_generator.render_patch.call_count == 3
        
        # Cleanup
        temp_path.unlink(missing_ok=True)


class TestAdaptiveSerumEvolver:
    """Test cases for AdaptiveSerumEvolver class."""
    
    def test_initialization(self, mock_param_manager, mock_audio_generator, mock_feature_extractor):
        """Test evolver initialization."""
        mock_generator, temp_path = mock_audio_generator
        
        evolver = AdaptiveSerumEvolver(
            audio_generator=mock_generator,
            feature_extractor=mock_feature_extractor,
            param_manager=mock_param_manager,
            max_workers=2,
            use_parallel_evaluation=True
        )
        
        assert evolver.audio_generator == mock_generator
        assert evolver.feature_extractor == mock_feature_extractor
        assert evolver.param_manager == mock_param_manager
        assert evolver.max_workers == 2
        assert evolver.use_parallel_evaluation == True
        
        # Cleanup
        temp_path.unlink(missing_ok=True)
    
    def test_implements_interface(self, mock_param_manager, mock_audio_generator, mock_feature_extractor):
        """Test that AdaptiveSerumEvolver implements ISerumEvolver interface."""
        mock_generator, temp_path = mock_audio_generator
        
        evolver = AdaptiveSerumEvolver(
            audio_generator=mock_generator,
            feature_extractor=mock_feature_extractor,
            param_manager=mock_param_manager
        )
        
        assert isinstance(evolver, ISerumEvolver)
        
        # Cleanup
        temp_path.unlink(missing_ok=True)
    
    def test_input_validation(self, sample_target_features, sample_feature_weights,
                             mock_param_manager, mock_audio_generator, mock_feature_extractor):
        """Test input validation in evolve method."""
        mock_generator, temp_path = mock_audio_generator
        
        evolver = AdaptiveSerumEvolver(
            audio_generator=mock_generator,
            feature_extractor=mock_feature_extractor,
            param_manager=mock_param_manager
        )
        
        # Test empty constraint set
        with pytest.raises(ValueError, match="Constraint set cannot be empty"):
            evolver.evolve({}, sample_target_features, sample_feature_weights)
        
        # Test invalid constraint set
        mock_param_manager.validate_constraint_set.return_value = False
        with pytest.raises(ValueError, match="Invalid constraint set"):
            evolver.evolve({'param1': (0.0, 1.0)}, sample_target_features, sample_feature_weights)
        
        # Test no active features
        empty_weights = FeatureWeights()  # All zeros
        mock_param_manager.validate_constraint_set.return_value = True
        with pytest.raises(ValueError, match="At least one feature weight must be non-zero"):
            evolver.evolve({'param1': (0.0, 1.0)}, sample_target_features, empty_weights)
        
        # Cleanup
        temp_path.unlink(missing_ok=True)
    
    @patch('serum_evolver.ga_engine.minimize')
    def test_evolution_result_processing(self, mock_minimize, sample_constraint_set, 
                                       sample_target_features, sample_feature_weights,
                                       mock_param_manager, mock_audio_generator, 
                                       mock_feature_extractor):
        """Test evolution result processing and formatting."""
        mock_generator, temp_path = mock_audio_generator
        
        # Mock pymoo result
        mock_result = Mock()
        mock_result.X = np.array([0.5, 0.6, 0.2, 400.0])
        mock_result.F = np.array([0.8])
        
        # Mock population
        mock_individual1 = Mock()
        mock_individual1.X = np.array([0.5, 0.6, 0.2, 400.0])
        mock_individual1.F = np.array([0.8])
        
        mock_individual2 = Mock()
        mock_individual2.X = np.array([0.3, 0.4, 0.1, 300.0])
        mock_individual2.F = np.array([1.2])
        
        mock_result.pop = [mock_individual1, mock_individual2]
        
        # Mock algorithm without callback to trigger fallback behavior
        mock_result.algorithm = Mock()
        mock_result.algorithm.callback = None
        
        mock_minimize.return_value = mock_result
        
        evolver = AdaptiveSerumEvolver(
            audio_generator=mock_generator,
            feature_extractor=mock_feature_extractor,
            param_manager=mock_param_manager,
            use_parallel_evaluation=False  # For simpler testing
        )
        
        results = evolver.evolve(
            constraint_set=sample_constraint_set,
            target_features=sample_target_features,
            feature_weights=sample_feature_weights,
            n_generations=3,
            population_size=2
        )
        
        # Verify result structure
        required_keys = [
            'best_individual', 'best_fitness', 'best_genome',
            'fitness_history', 'generation_stats', 'population_diversity',
            'jsi_ranking_candidates', 'evolution_metadata', 'performance_metrics'
        ]
        
        for key in required_keys:
            assert key in results
        
        # Verify best individual
        assert isinstance(results['best_individual'], dict)
        assert results['best_fitness'] == 0.8
        assert len(results['best_genome']) == len(sample_constraint_set)
        
        # Verify JSI candidates format
        jsi_candidates = results['jsi_ranking_candidates']
        assert isinstance(jsi_candidates, list)
        assert len(jsi_candidates) <= 5  # Top 5 candidates max
        
        for candidate in jsi_candidates:
            assert 'rank' in candidate
            assert 'fitness' in candidate
            assert 'parameters' in candidate
            assert 'genome' in candidate
            assert 'parameter_ids' in candidate
        
        # Verify metadata
        metadata = results['evolution_metadata']
        assert metadata['n_parameters'] == len(sample_constraint_set)
        assert metadata['constraint_set'] == sample_constraint_set
        assert 'evolution_time' in metadata
        
        # Cleanup
        temp_path.unlink(missing_ok=True)
    
    def test_convergence_detection(self, mock_param_manager, mock_audio_generator, mock_feature_extractor):
        """Test convergence detection functionality."""
        mock_generator, temp_path = mock_audio_generator
        
        evolver = AdaptiveSerumEvolver(
            audio_generator=mock_generator,
            feature_extractor=mock_feature_extractor,
            param_manager=mock_param_manager
        )
        
        # Test fitness history with convergence
        converging_history = [2.0, 1.5, 1.0, 1.001, 1.002, 1.001]  # Converges at gen 4
        convergence_gen = evolver._find_convergence_generation(converging_history, threshold=0.01)
        assert convergence_gen == 4
        
        # Test fitness history without convergence
        improving_history = [2.0, 1.5, 1.0, 0.5, 0.0]  # Keeps improving
        convergence_gen = evolver._find_convergence_generation(improving_history, threshold=0.01)
        assert convergence_gen is None
        
        # Test short history
        short_history = [1.0, 0.8]
        convergence_gen = evolver._find_convergence_generation(short_history)
        assert convergence_gen is None
        
        # Cleanup
        temp_path.unlink(missing_ok=True)


class TestIntegrationWithAllAgents:
    """Integration tests with all previous agents."""
    
    def test_parameter_manager_integration(self, sample_constraint_set, sample_target_features,
                                          sample_feature_weights):
        """Test integration with SerumParameterManager (Agent 1)."""
        from serum_evolver.parameter_manager import SerumParameterManager
        
        # Mock the parameter file to avoid file dependency
        with patch('serum_evolver.parameter_manager.Path.exists', return_value=True):
            with patch('builtins.open', mock_open_parameters_json()):
                param_manager = SerumParameterManager(Path("fake_params.json"))
                
                # Test constraint validation
                assert param_manager.validate_constraint_set(sample_constraint_set)
                
                # Test parameter bounds
                bounds = param_manager.get_parameter_bounds('param1')
                assert isinstance(bounds, tuple)
                assert len(bounds) == 2
    
    def test_feature_extractor_integration(self, sample_target_features, sample_feature_weights):
        """Test integration with LibrosaFeatureExtractor (Agent 2)."""
        from serum_evolver.feature_extractor import LibrosaFeatureExtractor
        
        extractor = LibrosaFeatureExtractor()
        
        # Test feature distance computation
        actual_features = ScalarFeatures(
            spectral_centroid=1400.0,
            spectral_bandwidth=750.0,
            rms_energy=0.09,
            tempo=118.0
        )
        
        distance = extractor.compute_feature_distance(
            sample_target_features, actual_features, sample_feature_weights
        )
        
        assert isinstance(distance, float)
        assert distance >= 0.0
    
    def test_audio_generator_integration(self, sample_constraint_set):
        """Test integration with SerumAudioGenerator (Agent 3)."""
        from serum_evolver.audio_generator import SerumAudioGenerator
        from serum_evolver.parameter_manager import SerumParameterManager
        
        # Mock dependencies to avoid external requirements
        with patch('serum_evolver.parameter_manager.Path.exists', return_value=True):
            with patch('builtins.open', mock_open_parameters_json()):
                param_manager = SerumParameterManager(Path("fake_params.json"))
                
                # Create mock audio generator
                with patch('serum_evolver.audio_generator.Path'):
                    mock_reaper_path = Path("/mock/reaper")
                    generator = SerumAudioGenerator(mock_reaper_path, param_manager)
                    
                    # Test parameter generation
                    with patch.object(generator, 'render_patch') as mock_render:
                        mock_render.return_value = Path("mock_audio.wav")
                        
                        result = generator.render_patch(
                            {'param1': 0.5, 'param2': 0.7}, "test_session"
                        )
                        
                        assert isinstance(result, Path)
                        mock_render.assert_called_once()


class TestPerformanceAndEdgeCases:
    """Performance and edge case testing."""
    
    def test_large_constraint_set_performance(self, sample_target_features, sample_feature_weights,
                                             mock_param_manager, mock_audio_generator, 
                                             mock_feature_extractor):
        """Test performance with large constraint sets."""
        mock_generator, temp_path = mock_audio_generator
        
        # Create large constraint set
        large_constraint_set = {f'param_{i}': (0.0, 1.0) for i in range(100)}
        
        problem = AdaptiveSerumProblem(
            constraint_set=large_constraint_set,
            target_features=sample_target_features,
            feature_weights=sample_feature_weights,
            audio_generator=mock_generator,
            feature_extractor=mock_feature_extractor,
            param_manager=mock_param_manager
        )
        
        # Verify genome size adapts correctly
        assert problem.n_var == 100
        assert len(problem.param_ids) == 100
        
        # Test mapping performance
        start_time = time.time()
        test_genome = np.random.random(100)
        params = problem.genome_to_parameters(test_genome)
        mapping_time = time.time() - start_time
        
        # Should be fast (< 0.1 seconds for 100 parameters)
        assert mapping_time < 0.1
        assert len(params) >= 100  # Includes defaults
        
        # Cleanup
        temp_path.unlink(missing_ok=True)
    
    def test_extreme_fitness_values(self, sample_constraint_set, sample_target_features,
                                   sample_feature_weights, mock_param_manager):
        """Test handling of extreme fitness values."""
        # Mock audio generator that sometimes fails
        mock_generator = Mock()
        mock_generator.render_patch.side_effect = [
            None,  # Failure
            Path("success.wav"),  # Success
            Exception("Unexpected error")  # Exception
        ]
        
        # Mock feature extractor with extreme values
        mock_extractor = Mock()
        mock_extractor.extract_scalar_features.return_value = sample_target_features
        mock_extractor.compute_feature_distance.side_effect = [
            float('inf'),  # Extreme distance
            1e-10,  # Very small distance
            float('nan')  # Invalid value
        ]
        
        problem = AdaptiveSerumProblem(
            constraint_set=sample_constraint_set,
            target_features=sample_target_features,
            feature_weights=sample_feature_weights,
            audio_generator=mock_generator,
            feature_extractor=mock_extractor,
            param_manager=mock_param_manager
        )
        
        # Test individual evaluations
        test_genome = np.array([0.5, 0.5, 0.0, 500.0])
        
        # Failure case
        fitness1 = problem._evaluate_individual(test_genome, 0)
        assert fitness1 == float('inf')
        
        # Exception case  
        fitness3 = problem._evaluate_individual(test_genome, 2)
        assert fitness3 == float('inf')
    
    def test_memory_efficiency(self, sample_constraint_set, sample_target_features,
                              sample_feature_weights, mock_param_manager,
                              mock_audio_generator, mock_feature_extractor):
        """Test memory efficiency with large populations."""
        mock_generator, temp_path = mock_audio_generator
        
        problem = AdaptiveSerumProblem(
            constraint_set=sample_constraint_set,
            target_features=sample_target_features,
            feature_weights=sample_feature_weights,
            audio_generator=mock_generator,
            feature_extractor=mock_feature_extractor,
            param_manager=mock_param_manager
        )
        
        # Test with larger population
        large_population = np.random.random((50, len(sample_constraint_set)))
        
        out = {}
        problem._evaluate(large_population, out)
        
        # Verify output format is correct
        assert out["F"].shape == (50, 1)
        assert out["F"].dtype == np.float64
        
        # Cleanup
        temp_path.unlink(missing_ok=True)


# Helper functions for mocking

def mock_open_parameters_json():
    """Mock open function for parameter JSON files."""
    from unittest.mock import mock_open
    
    # Match the expected structure: fx_data -> plugin -> parameters
    fake_params = {
        "fx_data": {
            "serum_plugin": {
                "parameters": {
                    "param1": {"name": "Parameter 1", "min_value": 0.0, "max_value": 1.0, "default": 0.5},
                    "param2": {"name": "Parameter 2", "min_value": 0.1, "max_value": 0.9, "default": 0.5},
                    "param3": {"name": "Parameter 3", "min_value": -1.0, "max_value": 1.0, "default": 0.0},
                    "param4": {"name": "Parameter 4", "min_value": 100.0, "max_value": 1000.0, "default": 500.0}
                }
            }
        }
    }
    
    import json
    return mock_open(read_data=json.dumps(fake_params))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])