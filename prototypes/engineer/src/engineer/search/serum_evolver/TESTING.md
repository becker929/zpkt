# SerumEvolver Testing Framework Documentation

This document provides comprehensive information about the SerumEvolver testing framework, including how to run tests, interpret results, and add new tests to the system.

## Table of Contents

1. [Overview](#overview)
2. [Test Suite Structure](#test-suite-structure)
3. [Running Tests](#running-tests)
4. [Test Categories](#test-categories)
5. [Performance Benchmarks](#performance-benchmarks)
6. [Test Fixtures and Utilities](#test-fixtures-and-utilities)
7. [Adding New Tests](#adding-new-tests)
8. [Troubleshooting](#troubleshooting)
9. [Coverage Reports](#coverage-reports)

## Overview

The SerumEvolver testing framework provides comprehensive validation of the complete system, including:

- **Unit Tests**: Individual component testing (90+ tests from previous agents)
- **Integration Tests**: Cross-component interaction validation
- **End-to-End Tests**: Complete workflow validation
- **Performance Tests**: Speed and memory usage benchmarks
- **Stress Tests**: System limits and robustness validation

The framework uses **pytest** as the primary testing tool with custom fixtures and utilities for mocking REAPER operations and generating test data.

## Test Suite Structure

```
serum_evolver/tests/
├── conftest.py                    # Shared pytest fixtures
├── fixtures/                     # Test utilities and mock data
│   ├── __init__.py
│   ├── mock_reaper.py            # REAPER operation mocking
│   └── test_data.py              # Test data generation
├── test_parameter_manager.py     # Parameter management tests
├── test_feature_extractor.py     # Audio feature extraction tests  
├── test_audio_generator.py       # Audio generation tests
├── test_ga_engine.py             # Genetic algorithm tests
├── test_integration_smoke.py     # Basic integration tests
├── test_integration_full.py      # Comprehensive integration tests
├── test_end_to_end.py            # Complete workflow tests
└── test_performance.py           # Performance and stress tests
```

## Running Tests

### Basic Test Execution

```bash
# Run all tests
python -m pytest serum_evolver/tests/ -v

# Run specific test category
python -m pytest serum_evolver/tests/test_integration_full.py -v

# Run performance tests (may take longer)
python -m pytest serum_evolver/tests/test_performance.py -v -s
```

### Test Selection and Filtering

```bash
# Run tests matching a pattern
python -m pytest serum_evolver/tests/ -k "integration" -v

# Run specific test class
python -m pytest serum_evolver/tests/test_integration_full.py::TestFullPipelineIntegration -v

# Run specific test method
python -m pytest serum_evolver/tests/test_integration_full.py::TestFullPipelineIntegration::test_basic_evolution_pipeline -v

# Skip slow tests
python -m pytest serum_evolver/tests/ -m "not slow" -v
```

### Parallel Test Execution

```bash
# Install pytest-xdist for parallel execution
pip install pytest-xdist

# Run tests in parallel
python -m pytest serum_evolver/tests/ -n auto -v
```

## Test Categories

### 1. Unit Tests (90+ tests)

Located in individual component test files:
- `test_parameter_manager.py`: Parameter validation, bounds checking, constraint sets
- `test_feature_extractor.py`: Audio feature extraction, distance calculation
- `test_audio_generator.py`: REAPER integration, audio generation
- `test_ga_engine.py`: Genetic algorithm, evolution engine

**Key Features:**
- Isolated component testing
- Mock external dependencies
- Edge case validation
- Performance requirements

### 2. Integration Tests

**Smoke Tests** (`test_integration_smoke.py`):
- Basic component initialization
- Simple integration workflows
- Configuration file compatibility

**Full Integration Tests** (`test_integration_full.py`):
- Complete pipeline validation
- Cross-component error handling  
- Data consistency verification
- Concurrent operation safety
- Memory management validation

### 3. End-to-End Tests

**Complete Workflow Tests** (`test_end_to_end.py`):
- User workflow simulation
- Sound design scenarios
- Iterative refinement
- Multi-objective optimization
- Production-scale testing

**Key Scenarios:**
- Basic user workflow: setup → evolve → results
- Sound design: targeting specific audio characteristics
- Iterative refinement: improving results over multiple runs
- Batch processing: multiple experiments
- Configuration-based workflows

### 4. Performance and Stress Tests

**Performance Benchmarks** (`test_performance.py`):
- Evolution speed measurement
- Memory usage patterns
- Component performance isolation
- Scaling analysis

**Stress Tests**:
- Large population sizes (up to 64 individuals)
- Long evolution runs (50+ generations)
- Concurrent execution (multiple simultaneous evolutions)
- Memory pressure scenarios
- High failure rate handling

## Performance Benchmarks

### Target Performance Metrics

| Component | Metric | Target |
|-----------|--------|---------|
| Evolution Cycle | Time | < 60s (8 individuals, 10 generations) |
| Parameter Validation | Speed | > 10,000 validations/second |
| Feature Extraction | Time | < 5s per audio file |
| Memory Usage | Peak | < 2GB typical operations |

### Benchmark Categories

1. **Speed Benchmarks**:
   - Evolution completion time
   - Parameter validation throughput
   - Feature extraction speed
   - Scaling with problem size

2. **Memory Benchmarks**:
   - Memory usage patterns
   - Memory leak detection
   - Peak memory consumption
   - Cleanup effectiveness

3. **Scalability Benchmarks**:
   - Parameter count scaling
   - Population size scaling
   - Generation count scaling
   - Concurrent operation scaling

### Running Performance Tests

```bash
# All performance tests
python -m pytest serum_evolver/tests/test_performance.py -v -s

# Specific benchmark category
python -m pytest serum_evolver/tests/test_performance.py::TestPerformanceBenchmarks -v -s

# Stress tests only
python -m pytest serum_evolver/tests/test_performance.py::TestStressTesting -v -s
```

## Test Fixtures and Utilities

### Core Fixtures (conftest.py)

- **`parameter_manager`**: Initialized SerumParameterManager
- **`feature_extractor`**: Initialized LibrosaFeatureExtractor
- **`audio_generator`**: SerumAudioGenerator with temp project
- **`ga_engine`**: Complete AdaptiveSerumEvolver system
- **`performance_monitor`**: Performance metrics collection
- **`concurrency_tester`**: Thread safety testing utilities

### Mock Utilities (fixtures/mock_reaper.py)

- **`MockReaperPatches`**: Context manager for REAPER operation mocking
- **`MockReaperSessionManager`**: Complete REAPER session simulation
- **`create_test_audio_files`**: Generate synthetic audio for testing
- **`create_performance_audio_file`**: Create audio files for benchmarks

### Test Data Generation (fixtures/test_data.py)

- **`ParameterTestDataGenerator`**: Generate parameter sets and constraints
- **`FeatureTestDataGenerator`**: Generate feature targets and weights
- **`EvolutionTestDataGenerator`**: Complete evolution scenarios
- **`BenchmarkDataGenerator`**: Performance testing datasets

## Adding New Tests

### 1. Unit Tests for New Components

```python
import pytest
from serum_evolver.new_component import NewComponent

class TestNewComponent:
    """Test suite for new component."""
    
    def test_component_initialization(self):
        """Test component initializes correctly."""
        component = NewComponent()
        assert component is not None
        
    def test_component_functionality(self):
        """Test core functionality."""
        component = NewComponent()
        result = component.process_data(test_data)
        assert result is not None
```

### 2. Integration Tests

```python
def test_new_component_integration(self, ga_engine, mock_audio_generation):
    """Test new component integrates with existing system."""
    
    # Setup test scenario
    constraint_set = {"1": (0.3, 0.7)}
    target_features = ScalarFeatures(spectral_centroid=2000.0)
    feature_weights = FeatureWeights(spectral_centroid=1.0)
    
    # Run integration test
    with MockReaperPatches():
        result = ga_engine.evolve(
            constraint_set, target_features, feature_weights,
            n_generations=3, population_size=4
        )
    
    # Validate integration
    assert "best_parameters" in result
    # Add component-specific validations
```

### 3. Performance Tests

```python
def test_new_component_performance(self, performance_monitor):
    """Benchmark new component performance."""
    
    performance_monitor.start()
    
    # Run performance test
    component = NewComponent()
    result = component.process_large_dataset(test_data)
    
    performance_monitor.stop()
    metrics = performance_monitor.get_metrics()
    
    # Validate performance requirements
    assert metrics["execution_time"] < MAX_TIME_SECONDS
    assert metrics["memory_usage_mb"] < MAX_MEMORY_MB
```

### Test Naming Conventions

- **Test files**: `test_component_name.py`
- **Test classes**: `TestComponentName`
- **Test methods**: `test_specific_functionality`
- **Integration tests**: `test_component_integration`
- **Performance tests**: `test_component_performance`

## Troubleshooting

### Common Test Failures

1. **REAPER Integration Issues**:
   ```
   FileNotFoundError: fx_parameters.json not found
   ```
   **Solution**: Tests use mocked REAPER operations. Ensure `mock_audio_generation` fixture is applied.

2. **Memory-Related Failures**:
   ```
   AssertionError: Excessive memory growth: 150.0MB
   ```
   **Solution**: Check for memory leaks, ensure proper cleanup in test teardown.

3. **Performance Test Failures**:
   ```
   AssertionError: Too slow 45.2s > 30.0s
   ```
   **Solution**: Performance tests may be sensitive to system load. Run on dedicated system or adjust thresholds.

4. **Concurrency Test Issues**:
   ```
   AssertionError: Concurrent execution had 2 errors
   ```
   **Solution**: Indicates thread safety issues. Check for shared state or improper locking.

### Debugging Techniques

1. **Verbose Output**:
   ```bash
   python -m pytest serum_evolver/tests/ -v -s --tb=long
   ```

2. **Run Single Test**:
   ```bash
   python -m pytest serum_evolver/tests/test_file.py::TestClass::test_method -v -s
   ```

3. **Add Debug Prints**:
   ```python
   def test_debug_example(self, ga_engine):
       print(f"Debug: Testing with {ga_engine}")
       # Test implementation
   ```

4. **Use Debugger**:
   ```bash
   python -m pytest serum_evolver/tests/test_file.py::test_method --pdb
   ```

### Test Environment Issues

1. **Dependencies**: Ensure all required packages are installed:
   ```bash
   pip install pytest numpy librosa pymoo psutil
   ```

2. **Python Version**: Tests require Python 3.8+

3. **Memory**: Performance tests may require 4GB+ available memory

4. **CPU**: Concurrent tests work best with 4+ CPU cores

## Coverage Reports

### Generating Coverage Reports

```bash
# Install coverage tool
pip install pytest-cov

# Generate basic coverage report
python -m pytest serum_evolver/tests/ --cov=serum_evolver

# Generate HTML coverage report
python -m pytest serum_evolver/tests/ --cov=serum_evolver --cov-report=html

# Generate coverage with missing lines
python -m pytest serum_evolver/tests/ --cov=serum_evolver --cov-report=term-missing
```

### Coverage Targets

| Component | Target Coverage |
|-----------|-----------------|
| Parameter Manager | > 95% |
| Feature Extractor | > 90% |
| Audio Generator | > 85% |
| GA Engine | > 90% |
| Integration Points | > 80% |

### Interpreting Coverage Reports

- **Lines Covered**: Percentage of code lines executed during tests
- **Missing Lines**: Specific lines not covered by tests
- **Branch Coverage**: Decision points (if/else) coverage
- **Function Coverage**: Percentage of functions called

## Test Data Management

### Temporary Files

- Tests create temporary files automatically
- Cleanup happens in fixture teardown
- Manual cleanup available via `cleanup_session` methods

### Test Data Persistence

```python
# Save test results for analysis
result_data = {
    "test_name": "performance_benchmark",
    "metrics": performance_metrics,
    "timestamp": time.time()
}

with open("test_results.json", "w") as f:
    json.dump(result_data, f, indent=2)
```

## Continuous Integration

### GitHub Actions Integration

```yaml
name: SerumEvolver Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.9
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov
      - name: Run tests
        run: |
          python -m pytest serum_evolver/tests/ --cov=serum_evolver
```

### Performance Regression Detection

```bash
# Run performance baseline
python -m pytest serum_evolver/tests/test_performance.py --benchmark-save=baseline

# Compare against baseline
python -m pytest serum_evolver/tests/test_performance.py --benchmark-compare=baseline
```

## Best Practices

### Test Development

1. **Write tests first** (TDD approach)
2. **Use descriptive test names**
3. **Test one thing per test method**
4. **Use fixtures for common setup**
5. **Mock external dependencies**
6. **Add performance tests for critical paths**

### Test Maintenance

1. **Keep tests up-to-date** with code changes
2. **Remove obsolete tests** when features are removed
3. **Update performance thresholds** as needed
4. **Document test requirements** and assumptions

### Performance Testing

1. **Run on consistent hardware** for comparable results
2. **Use dedicated test environment** for accurate measurements
3. **Set realistic performance thresholds**
4. **Monitor trends** over time, not just absolute values

---

**Last Updated**: September 2025
**Framework Version**: 1.0.0
**Python Version**: 3.8+