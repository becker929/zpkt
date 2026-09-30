"""
Mock REAPER integration utilities for testing.

This module provides comprehensive mocking of REAPER operations to enable
testing without requiring actual REAPER installation or execution.
"""

import json
import time
from pathlib import Path
from typing import Dict, Any, Optional, List
from unittest.mock import Mock, patch, MagicMock
import numpy as np
import tempfile
import wave


class MockReaperSessionManager:
    """Mock implementation of REAPER session management for testing."""
    
    def __init__(self, reaper_project_path: Path):
        self.reaper_project_path = reaper_project_path
        self.session_configs = {}
        self.execution_results = {}
        self.simulate_execution_time = 0.1  # Seconds
        self.simulate_failures = False
        self.failure_rate = 0.0  # 0.0 to 1.0
        
    def create_session_config(self, session_name: str, serum_parameters: Dict[str, float]) -> Path:
        """Create a mock session configuration file."""
        config = {
            "session_name": session_name,
            "render_configs": [
                {
                    "render_id": f"{session_name}_render",
                    "tracks": ["Track 1"],
                    "parameters": [
                        {"param_id": param_id, "value": value}
                        for param_id, value in serum_parameters.items()
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
        
        config_path = self.reaper_project_path / "session-configs" / f"{session_name}.json"
        config_path.parent.mkdir(exist_ok=True)
        
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
            
        self.session_configs[session_name] = config
        return config_path
    
    def execute_session(self, session_name: str) -> str:
        """Mock REAPER session execution."""
        time.sleep(self.simulate_execution_time)
        
        # Simulate occasional failures if configured
        if self.simulate_failures and np.random.random() < self.failure_rate:
            raise RuntimeError(f"Mock REAPER execution failed for session: {session_name}")
        
        # Create mock rendered audio file
        rendered_audio_path = self._create_mock_audio_file(session_name)
        
        # Store execution result
        self.execution_results[session_name] = {
            "status": "success",
            "audio_path": str(rendered_audio_path),
            "execution_time": self.simulate_execution_time
        }
        
        return str(rendered_audio_path)
    
    def _create_mock_audio_file(self, session_name: str) -> Path:
        """Create a synthetic audio file for testing."""
        render_dir = self.reaper_project_path / "renders" / f"{session_name}_params"
        render_dir.mkdir(parents=True, exist_ok=True)
        audio_path = render_dir / "untitled.wav"
        
        # Generate synthetic audio based on session parameters
        sample_rate = 44100
        duration = 2.0
        t = np.linspace(0, duration, int(sample_rate * duration))
        
        # Get parameters if available to influence synthetic audio
        session_params = self.session_configs.get(session_name, {}).get("render_configs", [{}])[0].get("parameters", [])
        param_dict = {p["param_id"]: p["value"] for p in session_params}
        
        # Create parameter-influenced audio
        base_freq = 440  # A4
        if "4" in param_dict:  # A Octave parameter
            octave_shift = (param_dict["4"] - 0.5) * 4  # -2 to +2 octaves
            base_freq *= (2 ** octave_shift)
        
        volume = 0.3
        if "1" in param_dict:  # Master Volume
            volume *= param_dict["1"]
        
        # Generate complex waveform
        audio_data = (
            volume * np.sin(2 * np.pi * base_freq * t) +
            volume * 0.5 * np.sin(2 * np.pi * base_freq * 2 * t) +  # Harmonic
            volume * 0.1 * np.random.normal(0, 0.05, len(t))  # Noise
        )
        
        # Add envelope
        envelope = np.exp(-t * 0.8)
        audio_data *= envelope
        
        # Save as WAV file
        with wave.open(str(audio_path), 'wb') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)
            
            # Convert to 16-bit integers
            audio_16bit = (audio_data * 32767).astype(np.int16)
            wav_file.writeframes(audio_16bit.tobytes())
        
        return audio_path
    
    def find_rendered_audio(self, session_name: str, timeout: float = 10.0) -> Optional[Path]:
        """Mock finding rendered audio files."""
        if session_name in self.execution_results:
            return Path(self.execution_results[session_name]["audio_path"])
        return None
    
    def cleanup_session_files(self, session_name: str):
        """Mock cleanup of session files."""
        # Remove from internal tracking
        if session_name in self.session_configs:
            del self.session_configs[session_name]
        if session_name in self.execution_results:
            del self.execution_results[session_name]
            
        # Remove actual files (they're in temp directories anyway)
        config_path = self.reaper_project_path / "session-configs" / f"{session_name}.json"
        if config_path.exists():
            config_path.unlink()


class MockReaperPatches:
    """Context manager for patching REAPER-related operations."""
    
    def __init__(self, 
                 simulate_execution_time: float = 0.1,
                 simulate_failures: bool = False,
                 failure_rate: float = 0.0):
        self.simulate_execution_time = simulate_execution_time
        self.simulate_failures = simulate_failures
        self.failure_rate = failure_rate
        self.patches = []
        
    def __enter__(self):
        """Start mocking REAPER operations."""
        # Mock subprocess.run for REAPER execution
        subprocess_patch = patch('subprocess.run')
        mock_subprocess = subprocess_patch.start()
        
        def mock_subprocess_run(*args, **kwargs):
            time.sleep(self.simulate_execution_time)
            
            if self.simulate_failures and np.random.random() < self.failure_rate:
                result = Mock()
                result.returncode = 1
                result.stdout = ""
                result.stderr = "Mock REAPER execution failed"
                return result
            
            result = Mock()
            result.returncode = 0
            result.stdout = "Session execution completed successfully"
            result.stderr = ""
            return result
            
        mock_subprocess.side_effect = mock_subprocess_run
        self.patches.append(subprocess_patch)
        
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop mocking REAPER operations."""
        for patch_obj in self.patches:
            patch_obj.stop()


def create_test_audio_files(output_dir: Path, count: int = 10) -> List[Path]:
    """Create multiple test audio files with different characteristics."""
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_files = []
    
    sample_rate = 44100
    duration = 2.0
    t = np.linspace(0, duration, int(sample_rate * duration))
    
    for i in range(count):
        # Create varied audio characteristics
        base_freq = 220 * (2 ** (i / 12))  # Chromatic scale starting from A3
        volume = 0.2 + (i / count) * 0.6  # Volume from 0.2 to 0.8
        
        # Generate audio with different spectral content
        if i % 4 == 0:  # Pure sine wave
            audio_data = volume * np.sin(2 * np.pi * base_freq * t)
        elif i % 4 == 1:  # Sine with harmonics
            audio_data = (
                volume * 0.6 * np.sin(2 * np.pi * base_freq * t) +
                volume * 0.3 * np.sin(2 * np.pi * base_freq * 2 * t) +
                volume * 0.1 * np.sin(2 * np.pi * base_freq * 3 * t)
            )
        elif i % 4 == 2:  # Square wave approximation
            audio_data = volume * np.sign(np.sin(2 * np.pi * base_freq * t))
        else:  # Noisy signal
            audio_data = (
                volume * 0.7 * np.sin(2 * np.pi * base_freq * t) +
                volume * 0.3 * np.random.normal(0, 0.1, len(t))
            )
        
        # Add envelope
        envelope = np.exp(-t * (0.5 + i * 0.1))
        audio_data *= envelope
        
        # Save audio file
        audio_path = output_dir / f"test_audio_{i:03d}.wav"
        with wave.open(str(audio_path), 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            
            audio_16bit = (audio_data * 32767).astype(np.int16)
            wav_file.writeframes(audio_16bit.tobytes())
            
        audio_files.append(audio_path)
    
    return audio_files


def create_performance_audio_file(output_path: Path, 
                                duration: float = 10.0,
                                complexity: str = "medium") -> Path:
    """Create an audio file for performance testing with specified complexity."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    sample_rate = 44100
    t = np.linspace(0, duration, int(sample_rate * duration))
    
    if complexity == "simple":
        # Simple sine wave
        audio_data = 0.3 * np.sin(2 * np.pi * 440 * t)
        
    elif complexity == "medium":
        # Multiple frequencies with envelope
        audio_data = (
            0.3 * np.sin(2 * np.pi * 220 * t) +
            0.25 * np.sin(2 * np.pi * 440 * t) +  
            0.2 * np.sin(2 * np.pi * 880 * t) +
            0.1 * np.random.normal(0, 0.05, len(t))
        )
        envelope = np.exp(-t * 0.3)
        audio_data *= envelope
        
    elif complexity == "high":
        # Complex multi-frequency signal with modulation
        carrier_freq = 440
        mod_freq = 5
        mod_depth = 0.5
        
        modulation = 1 + mod_depth * np.sin(2 * np.pi * mod_freq * t)
        
        audio_data = 0.0
        for harmonic in range(1, 8):  # 7 harmonics
            freq = carrier_freq * harmonic
            amplitude = 0.3 / harmonic  # Decreasing amplitude
            audio_data += amplitude * np.sin(2 * np.pi * freq * t) * modulation
            
        # Add filtered noise
        noise = np.random.normal(0, 0.05, len(t))
        # Simple low-pass filter (moving average)
        kernel_size = 10
        kernel = np.ones(kernel_size) / kernel_size
        filtered_noise = np.convolve(noise, kernel, mode='same')
        audio_data += 0.1 * filtered_noise
        
        # Complex envelope
        envelope = np.exp(-t * 0.2) * (1 + 0.3 * np.sin(2 * np.pi * 0.1 * t))
        audio_data *= envelope
        
    else:
        raise ValueError(f"Unknown complexity: {complexity}")
    
    # Normalize to prevent clipping
    audio_data = audio_data / np.max(np.abs(audio_data)) * 0.9
    
    # Save as WAV
    with wave.open(str(output_path), 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        
        audio_16bit = (audio_data * 32767).astype(np.int16)
        wav_file.writeframes(audio_16bit.tobytes())
    
    return output_path