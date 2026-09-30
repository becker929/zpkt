"""
Pytest configuration and shared fixtures for SerumeEvolver testing.

This file provides comprehensive testing infrastructure including:
- Mock utilities for REAPER integration
- Test data generation
- Performance measurement fixtures 
- Shared component instances
- Cross-agent integration helpers
"""

import pytest
import tempfile
import json
import numpy as np
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional
from unittest.mock import Mock, patch, MagicMock
import shutil
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import psutil
import os

# Serum evolver imports
from serum_evolver.interfaces import SerumParameters, ParameterConstraintSet, ScalarFeatures, FeatureWeights
from serum_evolver.parameter_manager import SerumParameterManager
from serum_evolver.feature_extractor import LibrosaFeatureExtractor  
from serum_evolver.audio_generator import SerumAudioGenerator
from serum_evolver.ga_engine import AdaptiveSerumEvolver


# =============================================================================
# Test Data and Constants
# =============================================================================

@pytest.fixture(scope="session")
def test_constants():
    """Test constants used across all integration tests."""
    return {
        "DEFAULT_SAMPLE_RATE": 44100,
        "DEFAULT_AUDIO_DURATION": 2.0,  # seconds
        "MAX_EVOLUTION_TIME": 60.0,  # seconds
        "MAX_MEMORY_USAGE_MB": 2000,
        "PERFORMANCE_TOLERANCE_PERCENT": 20,
        "TEST_PARAMETER_IDS": ["1", "4", "5", "6", "7"],  # Common Serum params
        "TARGET_FEATURES_BASIC": {
            "spectral_centroid": 2000.0,
            "rms_energy": 0.1,
            "spectral_bandwidth": 1500.0
        },
        "FEATURE_WEIGHTS_BASIC": {
            "spectral_centroid": 1.0,
            "rms_energy": 0.8,
            "spectral_bandwidth": 0.6
        }
    }


@pytest.fixture(scope="session") 
def fx_parameters_data():
    """Mock FX parameters data structure matching real REAPER format."""
    return {
        "fx_data": {
            "Serum_Track_VST3i:_Serum_Xfer_Records": {
                "name": "VST3i: Serum (Xfer Records)",
                "param_count": 7,
                "parameters": {
                    "1": {
                        "formatted_value": " 63% (-4.2 dB)",
                        "identifier": "0:0",
                        "max_value": 1.0,
                        "mid_value": 0.5,
                        "min_value": 0.0,
                        "name": "MasterVol",
                        "normalized_value": 0.63,
                        "value": 0.63
                    },
                    "4": {
                        "formatted_value": " 0",
                        "identifier": "3:3",
                        "max_value": 1.0,
                        "mid_value": 0.5,
                        "min_value": 0.0,
                        "name": "A Octave",
                        "normalized_value": 0.5,
                        "value": 0.5
                    },
                    "5": {
                        "formatted_value": " 0",
                        "identifier": "4:4",
                        "max_value": 1.0,
                        "mid_value": 0.5,
                        "min_value": 0.0,
                        "name": "A Fine",
                        "normalized_value": 0.5,
                        "value": 0.5
                    },
                    "6": {
                        "formatted_value": " 0",
                        "identifier": "5:5",
                        "max_value": 1.0,
                        "mid_value": 0.5,
                        "min_value": 0.0,
                        "name": "A Pan",
                        "normalized_value": 0.5,
                        "value": 0.5
                    },
                    "7": {
                        "formatted_value": " 50% (-6.0 dB)",
                        "identifier": "6:6",
                        "max_value": 1.0,
                        "mid_value": 0.5,
                        "min_value": 0.0,
                        "name": "A Level",
                        "normalized_value": 0.5,
                        "value": 0.5
                    },
                    "10": {
                        "formatted_value": " 0",
                        "identifier": "9:9",
                        "max_value": 1.0,
                        "mid_value": 0.5,
                        "min_value": 0.0,
                        "name": "OSC A WT Pos",
                        "normalized_value": 0.0,
                        "value": 0.0
                    },
                    "11": {
                        "formatted_value": " 0",
                        "identifier": "10:10",
                        "max_value": 1.0,
                        "mid_value": 0.5,
                        "min_value": 0.0,
                        "name": "OSC A Sub",
                        "normalized_value": 0.0,
                        "value": 0.0
                    }
                }
            }
        }
    }


# =============================================================================
# Component Fixtures
# =============================================================================

@pytest.fixture
def temp_reaper_project():
    """Create a temporary REAPER project directory with necessary files."""
    temp_dir = Path(tempfile.mkdtemp(prefix="serum_test_"))
    
    # Create directory structure
    (temp_dir / "renders").mkdir()
    (temp_dir / "session-configs").mkdir() 
    (temp_dir / "session-results").mkdir()
    
    # Create serum1.RPP file
    rpp_content = """<REAPER_PROJECT 0.1 "6.77/linux-x86_64" 1693856234
  RIPPLE 0
  GROUPOVERRIDE 0 0 0
  AUTOXFADE 1
  ENVATTACH 1
  MIXERUIFLAGS 11 48
  PEAKSEDGES 0
  FEEDBACK 0
  PANLAW 1
  PROJOFFS 0 0 0
  MAXPROJLEN 0 600
  GRID 3199 8 1 8 1 0 0 0
  TIMEMODE 1 5 -1 30 0 0 -1
  VIDEO_CONFIG 0 0 1000 
  PANMODE 3
  CURSOR 0
  ZOOM 100 0 0
  VZOOMEX 6 0
  USE_REC_CFG 0
  RECMODE 1
  SMPTESYNC 0 30 100 40 1000 300 0 0 1 0 0
  <METRONOME 6 2
    VOL 0.25 0.125
    FREQ 800 1600 1
    BEATLEN 4
    SAMPLES "" ""
    PATTERN 2863311530 2863311529
  >
  <RECORD_CFG 
    ZXZhdxgAAQ==
  >
  <APPLYFX_CFG 
  >
  RENDER_FILE ""
  RENDER_PATTERN ""
  RENDER_FMT 0 2 0
  RENDER_1X 0
  RENDER_RANGE 1 0 0 18 1000
  RENDER_RESAMPLE 3 0 1
  RENDER_ADDTOPROJ 0
  RENDER_STEMS 0
  RENDER_DITHER 0
  TIMELOCKMODE 1
  TEMPOENVLOCKMODE 1
  ITEMMIX 0
  DEFPITCHMODE 589824 0
  TAKELANE 1
  DEFVOL 0.75
  <TRACK {AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}
    NAME "Track 1"
    PEAKCOL 16576
    BEAT -1
    AUTOMODE 0
    VOLPAN 1 0 -1 -1 1
    MUTESOLO 0 0 0
    IPHASE 0
    PLAYOFFS 0 1
    ISBUS 0 0
    BUSCOMP 0 0 0 0 0
    SHOWINMIX 1 0.6667 0.5 1 0.5 0 0 0
    FREEMODE 0
    SEL 0
    REC 0 0 1 0 0 0 0 0
    VU 2
    TRACKHEIGHT 0 0 0 0 0 0
    INQ 0 0 0 0.5 100 0 0 100
    NCHAN 2
    FX 1
    TRACKID {AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}
    PERF 0
    MIDIOUT -1
    MAINSEND 1 0
    <FXCHAIN
      WNDRECT 584 390 948 596
      SHOW 0
      LASTSEL 0
      DOCKED 0
      BYPASS 0 0 0
      <VST "VST: Serum (Xfer Records)" "Serum.vst3" 0 "" 1397572948<56535453657275000000000000000000> ""
        ZXNlcu5e7f4CAAAAAQAAAAAAAAACAAAAAAAAAAIAAAABAAAAAgAAAAAAAAACAAJVU0UAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABTZXJ1bQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAAAA
        AGkAbgBpAHQAaQBhAGwAaQB6AGUAZAAAAAAAAA==
      >
    >
    <ITEM
      POSITION 0
      SNAPOFFS 0
      LENGTH 4
      LOOP 1
      ALLTAKES 0
      FADEIN 1 0.01 0 1 0 0 0
      FADEOUT 1 0.01 0 1 0 0 0
      MUTE 0 0
      SEL 0
      IGUID {BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}
      IID 1
      NAME "MIDI Item"
      VOLPAN 1 0 1 -1
      SOFFS 0
      PLAYRATE 1 1 0 -1 0 0.0025
      CHANMODE 0
      GUID {CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}
      <SOURCE MIDI
        HASDATA 1 960 QN
        E 0 90 3c 60
        E 3840 80 3c 00
      >
    >
  >
>"""
    with open(temp_dir / "serum1.RPP", "w") as f:
        f.write(rpp_content)
    
    yield temp_dir
    
    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture 
def temp_fx_params_file(fx_parameters_data):
    """Create temporary fx_parameters.json file."""
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    json.dump(fx_parameters_data, temp_file)
    temp_file.close()
    
    yield Path(temp_file.name)
    
    # Cleanup
    os.unlink(temp_file.name)


@pytest.fixture
def parameter_manager(temp_fx_params_file):
    """Initialized SerumParameterManager with test data."""
    return SerumParameterManager(temp_fx_params_file)


@pytest.fixture
def feature_extractor():
    """Initialized LibrosaFeatureExtractor."""
    return LibrosaFeatureExtractor()


@pytest.fixture
def audio_generator(temp_reaper_project, parameter_manager):
    """Initialized SerumAudioGenerator with temporary project."""
    return SerumAudioGenerator(temp_reaper_project, parameter_manager)


@pytest.fixture
def ga_engine(audio_generator, feature_extractor, parameter_manager):
    """Initialized AdaptiveSerumEvolver with all components."""
    return AdaptiveSerumEvolver(audio_generator, feature_extractor, parameter_manager)


# =============================================================================
# Mock Fixtures
# =============================================================================

@pytest.fixture
def mock_reaper_execution():
    """Mock REAPER execution to avoid actual REAPER calls."""
    with patch('subprocess.run') as mock_run:
        # Simulate successful REAPER execution
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Session execution completed"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        yield mock_run


@pytest.fixture
def mock_audio_generation():
    """Mock audio generation that creates synthetic audio files."""
    def create_mock_audio_file(output_path: Path) -> Path:
        """Create a synthetic audio file for testing."""
        # Generate 2 seconds of synthetic audio data
        sample_rate = 44100
        duration = 2.0
        t = np.linspace(0, duration, int(sample_rate * duration))
        
        # Create a complex synthetic audio signal
        frequency1 = 440  # A4
        frequency2 = 880  # A5
        audio_data = (
            0.3 * np.sin(2 * np.pi * frequency1 * t) +
            0.2 * np.sin(2 * np.pi * frequency2 * t) +
            0.1 * np.random.normal(0, 0.1, len(t))  # Add some noise
        )
        
        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save as WAV file using basic format
        import wave
        with wave.open(str(output_path), 'wb') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)
            
            # Convert to 16-bit integers
            audio_16bit = (audio_data * 32767).astype(np.int16)
            wav_file.writeframes(audio_16bit.tobytes())
        
        return output_path
    
    with patch('serum_evolver.audio_generator.ReaperSessionManager.execute_session') as mock_execute:
        def mock_execute_side_effect(session_name) -> tuple:
            # Create mock rendered audio file
            mock_audio_path = Path(f"/tmp/{session_name}_untitled.wav")
            create_mock_audio_file(mock_audio_path)
            return True, mock_audio_path  # Return (success, audio_path) tuple
            
        mock_execute.side_effect = mock_execute_side_effect
        yield mock_execute


@pytest.fixture
def mock_performance_audio_data():
    """Generate larger synthetic audio data for performance testing."""
    def generate_performance_audio(duration_seconds: float = 10.0) -> np.ndarray:
        sample_rate = 44100
        t = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds))
        
        # Create complex multi-frequency audio
        audio_data = (
            0.3 * np.sin(2 * np.pi * 220 * t) +  # A3
            0.25 * np.sin(2 * np.pi * 440 * t) +  # A4  
            0.2 * np.sin(2 * np.pi * 880 * t) +   # A5
            0.15 * np.sin(2 * np.pi * 1760 * t) + # A6
            0.1 * np.random.normal(0, 0.05, len(t))  # Noise
        )
        
        # Add some dynamics
        envelope = np.exp(-t * 0.5)  # Exponential decay
        audio_data *= envelope
        
        return audio_data
    
    return generate_performance_audio


# =============================================================================
# Performance and Memory Monitoring Fixtures
# =============================================================================

@pytest.fixture
def performance_monitor():
    """Monitor performance metrics during test execution."""
    class PerformanceMonitor:
        def __init__(self):
            self.start_time = None
            self.end_time = None 
            self.start_memory = None
            self.peak_memory = None
            self.process = psutil.Process()
            
        def start(self):
            self.start_time = time.time()
            self.start_memory = self.process.memory_info().rss / 1024 / 1024  # MB
            self.peak_memory = self.start_memory
            
        def update_peak_memory(self):
            current_memory = self.process.memory_info().rss / 1024 / 1024  # MB
            if current_memory > self.peak_memory:
                self.peak_memory = current_memory
                
        def stop(self):
            self.end_time = time.time()
            self.update_peak_memory()
            
        @property
        def execution_time(self) -> float:
            if self.start_time and self.end_time:
                return self.end_time - self.start_time
            return 0.0
            
        @property 
        def memory_usage_mb(self) -> float:
            return self.peak_memory - self.start_memory if self.peak_memory and self.start_memory else 0.0
            
        def get_metrics(self) -> Dict[str, float]:
            return {
                "execution_time": self.execution_time,
                "memory_usage_mb": self.memory_usage_mb,
                "peak_memory_mb": self.peak_memory or 0.0,
                "start_memory_mb": self.start_memory or 0.0
            }
    
    return PerformanceMonitor()


@pytest.fixture
def concurrency_tester():
    """Helper for testing concurrent operations."""
    class ConcurrencyTester:
        def __init__(self):
            self.results = []
            self.errors = []
            self.lock = threading.Lock()
            
        def run_concurrent(self, func, args_list: List[Tuple], max_workers: int = 4):
            """Run function concurrently with different argument sets."""
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = []
                
                for args in args_list:
                    future = executor.submit(self._safe_execute, func, args)
                    futures.append(future)
                
                # Wait for all to complete
                for future in futures:
                    future.result()  # This will raise any exceptions
                    
        def _safe_execute(self, func, args):
            try:
                result = func(*args)
                with self.lock:
                    self.results.append(result)
            except Exception as e:
                with self.lock:
                    self.errors.append(e)
                raise
                
        def get_results(self) -> List[Any]:
            return self.results.copy()
            
        def get_errors(self) -> List[Exception]:
            return self.errors.copy()
            
        def assert_no_errors(self):
            assert len(self.errors) == 0, f"Concurrent execution had {len(self.errors)} errors: {self.errors}"
            
        def assert_all_successful(self, expected_count: int):
            self.assert_no_errors()
            assert len(self.results) == expected_count, f"Expected {expected_count} results, got {len(self.results)}"
    
    return ConcurrencyTester()


# =============================================================================  
# Test Data Generation Helpers
# =============================================================================

@pytest.fixture
def test_constraint_generator(test_constants):
    """Generate various constraint sets for testing."""
    def generate_constraints(complexity: str = "simple") -> ParameterConstraintSet:
        param_ids = test_constants["TEST_PARAMETER_IDS"]
        
        if complexity == "simple":
            return {"4": (0.2, 0.8)}  # Single parameter
        elif complexity == "medium":
            return {
                "1": (0.3, 0.9),    # MasterVol
                "4": (0.2, 0.8),    # A Octave 
                "7": (0.4, 0.7)     # A Level
            }
        elif complexity == "complex":
            return {param_id: (0.1, 0.9) for param_id in param_ids}
        elif complexity == "large":
            # Generate 50+ parameter constraint set
            constraints = {}
            for i in range(1, 51):  # Parameter IDs 1-50
                constraints[str(i)] = (np.random.uniform(0.0, 0.3), np.random.uniform(0.7, 1.0))
            return constraints
        else:
            raise ValueError(f"Unknown complexity: {complexity}")
    
    return generate_constraints


@pytest.fixture  
def test_features_generator(test_constants):
    """Generate various feature sets for testing."""
    def generate_features(feature_type: str = "basic") -> Tuple[ScalarFeatures, FeatureWeights]:
        if feature_type == "basic":
            target = ScalarFeatures(
                spectral_centroid=test_constants["TARGET_FEATURES_BASIC"]["spectral_centroid"],
                rms_energy=test_constants["TARGET_FEATURES_BASIC"]["rms_energy"], 
                spectral_bandwidth=test_constants["TARGET_FEATURES_BASIC"]["spectral_bandwidth"]
            )
            weights = FeatureWeights(
                spectral_centroid=test_constants["FEATURE_WEIGHTS_BASIC"]["spectral_centroid"],
                rms_energy=test_constants["FEATURE_WEIGHTS_BASIC"]["rms_energy"],
                spectral_bandwidth=test_constants["FEATURE_WEIGHTS_BASIC"]["spectral_bandwidth"]
            )
        elif feature_type == "multi":
            target = ScalarFeatures(
                spectral_centroid=2500.0,
                spectral_bandwidth=1800.0,
                spectral_rolloff=3000.0,
                rms_energy=0.15,
                zero_crossing_rate=0.1,
                chroma_mean=0.7
            )
            weights = FeatureWeights(
                spectral_centroid=1.0,
                spectral_bandwidth=0.8,
                spectral_rolloff=0.6, 
                rms_energy=0.9,
                zero_crossing_rate=0.4,
                chroma_mean=0.5
            )
        elif feature_type == "all":
            target = ScalarFeatures(
                spectral_centroid=2000.0,
                spectral_bandwidth=1500.0,
                spectral_rolloff=4000.0,
                spectral_contrast=0.8,
                spectral_flatness=0.3,
                zero_crossing_rate=0.1,
                rms_energy=0.2,
                chroma_mean=0.6,
                tonnetz_mean=0.4,
                mfcc_mean=15.0,
                tempo=120.0
            )
            weights = FeatureWeights(
                spectral_centroid=1.0,
                spectral_bandwidth=0.9,
                spectral_rolloff=0.8,
                spectral_contrast=0.7,
                spectral_flatness=0.6,
                zero_crossing_rate=0.5,
                rms_energy=0.9,
                chroma_mean=0.6,
                tonnetz_mean=0.4,
                mfcc_mean=0.3,
                tempo=0.2
            )
        else:
            raise ValueError(f"Unknown feature_type: {feature_type}")
            
        return target, weights
    
    return generate_features


# =============================================================================
# Integration Test Helpers  
# =============================================================================

@pytest.fixture
def integration_validator():
    """Validate integration between components."""
    class IntegrationValidator:
        def __init__(self):
            self.validation_results = []
            
        def validate_parameter_flow(self, param_manager, audio_generator, constraint_set):
            """Validate parameters flow correctly between components."""
            results = {"parameter_flow": False, "details": []}
            
            try:
                # Test parameter generation
                random_params = audio_generator._generate_random_parameters(constraint_set)
                results["details"].append(f"Generated {len(random_params)} parameters")
                
                # Test parameter validation
                all_valid = all(
                    param_manager.validate_parameter_value(param_id, value)
                    for param_id, value in random_params.items()
                )
                results["details"].append(f"All parameters valid: {all_valid}")
                
                # Test constraint validation
                constraints_valid = param_manager.validate_constraint_set(constraint_set)
                results["details"].append(f"Constraints valid: {constraints_valid}")
                
                results["parameter_flow"] = all_valid and constraints_valid
                
            except Exception as e:
                results["details"].append(f"Error: {str(e)}")
                
            self.validation_results.append(results)
            return results
            
        def validate_audio_feature_flow(self, audio_generator, feature_extractor, params, weights):
            """Validate audio generation to feature extraction flow."""
            results = {"audio_feature_flow": False, "details": []}
            
            try:
                # Generate audio (mocked)
                session_name = "test_audio_feature_flow"
                with patch('serum_evolver.audio_generator.ReaperSessionManager.execute_session') as mock_execute:
                    mock_execute.return_value = (True, Path("/tmp/test_audio.wav"))
                    
                    # Create synthetic audio file
                    import wave
                    sample_rate = 44100
                    duration = 2.0
                    t = np.linspace(0, duration, int(sample_rate * duration))
                    audio_data = 0.3 * np.sin(2 * np.pi * 440 * t)
                    
                    with wave.open("/tmp/test_audio.wav", 'wb') as wav_file:
                        wav_file.setnchannels(1)
                        wav_file.setsampwidth(2) 
                        wav_file.setframerate(sample_rate)
                        audio_16bit = (audio_data * 32767).astype(np.int16)
                        wav_file.writeframes(audio_16bit.tobytes())
                    
                    audio_path = audio_generator.render_patch(params, "test_session")
                    results["details"].append(f"Audio generated: {audio_path}")
                    
                    # Extract features
                    features = feature_extractor.extract_scalar_features(Path(audio_path), weights)
                    results["details"].append(f"Features extracted: {len(features.__dict__)} features")
                    
                    # Cleanup
                    os.unlink("/tmp/test_audio.wav")
                    
                    results["audio_feature_flow"] = True
                    
            except Exception as e:
                results["details"].append(f"Error: {str(e)}")
                if os.path.exists("/tmp/test_audio.wav"):
                    os.unlink("/tmp/test_audio.wav")
                    
            self.validation_results.append(results)
            return results
            
        def validate_full_pipeline(self, ga_engine, constraint_set, target_features, feature_weights):
            """Validate complete pipeline integration."""  
            results = {"full_pipeline": False, "details": []}
            
            try:
                # Run short evolution
                evolution_result = ga_engine.evolve(
                    constraint_set=constraint_set,
                    target_features=target_features,
                    feature_weights=feature_weights,
                    n_generations=2,
                    population_size=4
                )
                
                results["details"].append(f"Evolution completed: {evolution_result['converged']}")
                results["details"].append(f"Best fitness: {evolution_result['best_fitness']}")
                results["details"].append(f"Generations: {evolution_result['generations_run']}")
                
                results["full_pipeline"] = True
                
            except Exception as e:
                results["details"].append(f"Error: {str(e)}")
                
            self.validation_results.append(results)
            return results
            
        def get_validation_summary(self) -> Dict[str, Any]:
            """Get summary of all validation results."""
            return {
                "total_validations": len(self.validation_results),
                "successful_validations": sum(1 for r in self.validation_results if any(r.values())),
                "results": self.validation_results
            }
    
    return IntegrationValidator()