from abc import ABC, abstractmethod
from typing import Tuple, Optional, Dict, Any
from pathlib import Path
import json
import uuid
import random
import subprocess
import time
import logging

from .interfaces import SerumParameters, ParameterConstraintSet
from .parameter_manager import ISerumParameterManager


class IAudioGenerator(ABC):
    """Interface for audio generation from Serum parameters."""

    @abstractmethod
    def create_random_patch(self, constraint_set: ParameterConstraintSet) -> Tuple[SerumParameters, Path]:
        """Generate random patch within constraints and render audio."""
        pass

    @abstractmethod
    def render_patch(self, serum_params: SerumParameters,
                    session_name: str) -> Path:
        """Render specific Serum parameters to audio file."""
        pass


class ReaperSessionManager:
    """Manages REAPER session configuration and execution for Serum audio generation."""
    
    def __init__(self, reaper_project_path: Path):
        """
        Initialize REAPER session manager.
        
        Args:
            reaper_project_path: Path to REAPER project directory
        """
        self.reaper_project_path = Path(reaper_project_path)
        self.session_configs_dir = self.reaper_project_path / "session-configs"
        self.renders_dir = self.reaper_project_path / "renders"
        self.session_results_dir = self.reaper_project_path / "session-results"
        self.logger = logging.getLogger(__name__)
        
        # Ensure required directories exist
        self._ensure_directories()
    
    def _ensure_directories(self):
        """Ensure required directories exist."""
        for directory in [self.session_configs_dir, self.renders_dir, self.session_results_dir]:
            directory.mkdir(parents=True, exist_ok=True)
    
    def create_session_config(self, session_name: str, serum_params: SerumParameters) -> Path:
        """
        Create a REAPER session configuration file for Serum parameter rendering.
        
        Args:
            session_name: Unique session name
            serum_params: Serum parameters to set
            
        Returns:
            Path to created session config file
        """
        render_id = f"{session_name}_{uuid.uuid4().hex[:8]}"
        
        # Build parameters list for REAPER
        parameters = []
        for param_id, value in serum_params.items():
            # Convert parameter ID to parameter name using existing format
            param_name = self._get_param_name_from_id(param_id)
            parameters.append({
                "track": "0",
                "fx": "Serum",
                "param": param_name,
                "value": float(value)
            })
        
        # Create session configuration matching the existing format
        session_config = {
            "session_name": session_name,
            "render_configs": [{
                "render_id": render_id,
                "tracks": [{
                    "index": 0,
                    "name": "Serum Track",
                    "fx_chain": [{
                        "name": "Serum",
                        "plugin_name": "Serum"
                    }]
                }],
                "parameters": parameters,
                "midi_files": {
                    "0": "test_melody.mid"  # Standard MIDI file for consistent note
                },
                "render_options": {
                    "sample_rate": 44100,
                    "channels": 2,
                    "render_format": "",
                    "bpm": 148,  # Standardized BPM
                    "note": "C4",  # Middle C
                    "duration": "whole"  # Whole note duration
                }
            }]
        }
        
        # Write session config file
        config_path = self.session_configs_dir / f"{session_name}.json"
        with open(config_path, 'w') as f:
            json.dump(session_config, f, indent=2)
        
        self.logger.info(f"Created session config: {config_path}")
        return config_path
    
    def _get_param_name_from_id(self, param_id: str) -> str:
        """
        Convert parameter ID to parameter name.
        For now, this assumes the param_id is already a valid parameter name.
        In a full implementation, this would use the parameter manager to lookup names.
        
        Args:
            param_id: Parameter identifier
            
        Returns:
            Parameter name for REAPER
        """
        # Simple mapping for common parameters - in practice this would use the parameter manager
        param_name_mapping = {
            "1": "MasterVol",
            "2": "A Vol",
            "3": "A Pan", 
            "4": "A Octave",
            "5": "A Fine",
            # Add more mappings as needed
        }
        
        return param_name_mapping.get(param_id, param_id)
    
    def execute_session(self, session_config_path: Path, timeout: int = 120) -> Tuple[bool, Optional[Path]]:
        """
        Execute REAPER session and return rendered audio path.
        
        Args:
            session_config_path: Path to session config file
            timeout: Execution timeout in seconds
            
        Returns:
            Tuple of (success, audio_file_path)
        """
        try:
            # Change to REAPER project directory for execution
            original_cwd = Path.cwd()
            reaper_cwd = self.reaper_project_path
            
            # Import and use the existing REAPER execution system
            import sys
            sys.path.append(str(reaper_cwd))
            
            # Change working directory to REAPER directory
            import os
            os.chdir(reaper_cwd)
            
            try:
                # Import the main REAPER execution function
                from main import execute_reaper_with_session, monitor_reaper_execution
                
                # Execute REAPER session
                self.logger.info(f"Executing REAPER session: {session_config_path.name}")
                result = execute_reaper_with_session(session_config_path.name)
                
                if result.returncode == 0:
                    # Look for rendered audio files
                    audio_path = self._find_rendered_audio(session_config_path.stem)
                    if audio_path and audio_path.exists():
                        self.logger.info(f"Session completed successfully, audio: {audio_path}")
                        return True, audio_path
                    else:
                        self.logger.warning("Session completed but no audio file found")
                        return False, None
                else:
                    self.logger.error(f"REAPER execution failed: {result.stderr}")
                    return False, None
                    
            except Exception as e:
                self.logger.error(f"Error executing REAPER session: {e}")
                return False, None
            
            finally:
                # Restore original working directory
                os.chdir(original_cwd)
                
        except Exception as e:
            self.logger.error(f"Failed to execute session: {e}")
            return False, None
    
    def _find_rendered_audio(self, session_name: str) -> Optional[Path]:
        """
        Find the rendered audio file for a session.
        
        Args:
            session_name: Name of the session
            
        Returns:
            Path to rendered audio file or None if not found
        """
        # Look for audio files in renders directory
        for render_dir in self.renders_dir.iterdir():
            if render_dir.is_dir() and session_name in render_dir.name:
                for audio_file in render_dir.glob("*.wav"):
                    return audio_file
        
        # Also check for files directly in renders directory
        for audio_file in self.renders_dir.glob(f"*{session_name}*.wav"):
            return audio_file
            
        return None
    
    def cleanup_session_files(self, session_name: str):
        """
        Clean up temporary files for a session.
        
        Args:
            session_name: Name of the session to clean up
        """
        try:
            # Remove session config
            config_file = self.session_configs_dir / f"{session_name}.json"
            if config_file.exists():
                config_file.unlink()
                self.logger.debug(f"Removed session config: {config_file}")
            
            # Remove session results
            for result_file in self.session_results_dir.glob(f"*{session_name}*"):
                if result_file.is_file():
                    result_file.unlink()
                    self.logger.debug(f"Removed session result: {result_file}")
                    
        except Exception as e:
            self.logger.warning(f"Error cleaning up session files: {e}")


class SerumAudioGenerator(IAudioGenerator):
    """Implementation of audio generation from Serum parameters using REAPER."""
    
    def __init__(self, reaper_project_path: Path, param_manager: ISerumParameterManager):
        """
        Initialize the Serum audio generator.
        
        Args:
            reaper_project_path: Path to REAPER project directory
            param_manager: Parameter manager for validation and defaults
        """
        self.reaper_project_path = Path(reaper_project_path)
        self.param_manager = param_manager
        self.reaper_session_manager = ReaperSessionManager(reaper_project_path)
        self.logger = logging.getLogger(__name__)
        
        # Configure logging if not already configured
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
    
    def create_random_patch(self, constraint_set: ParameterConstraintSet) -> Tuple[SerumParameters, Path]:
        """
        Generate random patch within constraints and render audio.
        
        Args:
            constraint_set: Dictionary mapping parameter IDs to (min, max) constraint tuples
            
        Returns:
            Tuple of (generated_parameters, audio_file_path)
            
        Raises:
            ValueError: If constraint set is invalid
            RuntimeError: If audio rendering fails
        """
        # Validate constraint set
        if not self.param_manager.validate_constraint_set(constraint_set):
            raise ValueError("Invalid constraint set provided")
        
        # Generate random parameters within constraints
        serum_params = self._generate_random_parameters(constraint_set)
        
        # Get default parameters for unconstrained parameters
        default_params = self.param_manager.get_default_parameters()
        
        # Merge: constrained parameters override defaults
        full_params = default_params.copy()
        full_params.update(serum_params)
        
        # Generate unique session name
        session_name = f"random_{uuid.uuid4().hex[:8]}"
        
        # Render audio
        audio_path = self.render_patch(full_params, session_name)
        
        return serum_params, audio_path
    
    def render_patch(self, serum_params: SerumParameters, session_name: str) -> Path:
        """
        Render specific Serum parameters to audio file.
        
        Args:
            serum_params: Dictionary mapping parameter IDs to values
            session_name: Unique session identifier
            
        Returns:
            Path to rendered audio file
            
        Raises:
            ValueError: If parameters are invalid
            RuntimeError: If rendering fails
        """
        # Validate all parameters
        for param_id, value in serum_params.items():
            if not self.param_manager.validate_parameter_value(param_id, value):
                raise ValueError(f"Invalid parameter value: {param_id}={value}")
        
        try:
            # Create session configuration
            config_path = self.reaper_session_manager.create_session_config(session_name, serum_params)
            
            # Execute REAPER session
            success, audio_path = self.reaper_session_manager.execute_session(config_path)
            
            if not success or not audio_path:
                raise RuntimeError(f"Failed to render audio for session {session_name}")
            
            self.logger.info(f"Successfully rendered audio: {audio_path}")
            return audio_path
            
        except Exception as e:
            self.logger.error(f"Error rendering patch {session_name}: {e}")
            # Clean up on failure
            self.reaper_session_manager.cleanup_session_files(session_name)
            raise RuntimeError(f"Audio rendering failed: {e}")
    
    def _generate_random_parameters(self, constraint_set: ParameterConstraintSet) -> SerumParameters:
        """
        Generate random parameter values within specified constraints.
        
        Args:
            constraint_set: Dictionary mapping parameter IDs to (min, max) tuples
            
        Returns:
            Dictionary of randomly generated parameter values
        """
        random_params = {}
        
        for param_id, (min_val, max_val) in constraint_set.items():
            # Generate random value within constraints
            random_value = random.uniform(min_val, max_val)
            random_params[param_id] = random_value
            
            self.logger.debug(f"Generated random value for {param_id}: {random_value} in [{min_val}, {max_val}]")
        
        return random_params
    
    def cleanup_session(self, session_name: str):
        """
        Clean up temporary files for a session.
        
        Args:
            session_name: Name of the session to clean up
        """
        self.reaper_session_manager.cleanup_session_files(session_name)