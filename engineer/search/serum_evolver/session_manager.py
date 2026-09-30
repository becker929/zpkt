#!/usr/bin/env python3
"""
Session-based audio generation for genetic algorithm experiments.

Implements proper directory structure:
renders/<experiment>/<session>/target/ and renders/<experiment>/<session>/renders/
"""

import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import json
import importlib.util
import os

from .interfaces import SerumParameters
from .parameter_manager import ISerumParameterManager

logger = logging.getLogger(__name__)


class ExperimentSessionManager:
    """
    Manages experiment sessions with proper directory structure and batch rendering.
    """
    
    def __init__(self, reaper_project_path: Path, param_manager: ISerumParameterManager, 
                 experiment_name: str, target_audio_path: Optional[Path] = None,
                 artifact_manager=None):
        """
        Initialize experiment session manager.
        
        Args:
            reaper_project_path: Path to REAPER project directory
            param_manager: Parameter manager for validation
            experiment_name: Name of the experiment (e.g., "large_serum_experiment")
            target_audio_path: Optional reference audio for target features
            artifact_manager: Optional ArtifactManager for organizing experiment results
        """
        self.reaper_project_path = Path(reaper_project_path)
        self.param_manager = param_manager
        self.experiment_name = experiment_name
        self.artifact_manager = artifact_manager
        
        # Create experiment directory structure in REAPER (temporary working directory)
        self.experiment_dir = self.reaper_project_path / "renders" / experiment_name
        self.experiment_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup target audio at experiment level
        self.target_dir = self.experiment_dir / "target"
        self.target_audio_path = None
        
        if target_audio_path and target_audio_path.exists():
            self.target_dir.mkdir(exist_ok=True)
            self.target_audio_path = self.target_dir / "reference.wav"
            
            # Only copy if source and destination are different files
            if target_audio_path.resolve() != self.target_audio_path.resolve():
                import shutil
                shutil.copy2(target_audio_path, self.target_audio_path)
                logger.info(f"Copied target audio to {self.target_audio_path}")
            else:
                self.target_audio_path = target_audio_path
                logger.info(f"Target audio already at correct location: {self.target_audio_path}")
            
            # Also set target audio in artifact manager if provided (only if not already managed)
            if self.artifact_manager and "experiment_results" not in str(target_audio_path):
                self.artifact_manager.set_target_audio(target_audio_path)
        
        logger.info(f"Initialized experiment session manager: {experiment_name}")
    
    def create_generation_session(self, generation: int, population_params: List[SerumParameters]) -> Path:
        """
        Create a complete session for a generation with all individuals.
        
        Args:
            generation: Generation number (1-based)
            population_params: List of parameter sets for all individuals in generation
            
        Returns:
            Path to session directory
        """
        session_name = f"generation_{generation:03d}"
        session_dir = self.experiment_dir / session_name
        
        # Clean and recreate session directory
        if session_dir.exists():
            import shutil
            shutil.rmtree(session_dir)
        session_dir.mkdir(parents=True)
        
        logger.info(f"Creating session {session_name} with {len(population_params)} individuals")
        
        # Create renders directory structure
        renders_dir = session_dir / "renders"
        renders_dir.mkdir()
        
        for i, params in enumerate(population_params):
            individual_dir = renders_dir / f"individual_{i:03d}"
            individual_dir.mkdir()
        
        # Create session configuration for batch rendering
        session_config = self._create_batch_session_config(
            session_name, population_params, renders_dir
        )
        
        # Write session config
        config_path = self.reaper_project_path / "session-configs" / f"{session_name}.json"
        config_path.parent.mkdir(exist_ok=True)
        
        with open(config_path, 'w') as f:
            json.dump(session_config, f, indent=2)
        
        logger.info(f"Created session config: {config_path}")
        return session_dir
    
    def _create_batch_session_config(self, session_name: str, population_params: List[SerumParameters], 
                                   renders_dir: Path) -> Dict:
        """
        Create session configuration for batch rendering all individuals.
        
        Args:
            session_name: Name of the session
            population_params: Parameters for all individuals
            renders_dir: Base renders directory
            
        Returns:
            Session configuration dictionary
        """
        render_configs = []
        
        for i, params in enumerate(population_params):
            individual_name = f"individual_{i:03d}"
            render_id = f"{session_name}_{individual_name}_{int(time.time() * 1000) % 100000:05d}"
            
            # Create individual render config
            render_config = {
                "render_id": render_id,
                "tracks": [
                    {
                        "index": 0,
                        "name": "Serum Track",
                        "fx_chain": [
                            {
                                "name": "Serum",
                                "plugin_name": "Serum"
                            }
                        ]
                    }
                ],
                "parameters": [],
                "midi_files": {
                    "0": "test_melody.mid"
                },
                "render_options": {
                    "sample_rate": 44100,
                    "channels": 2,
                    "render_format": "",
                    "bpm": 148,
                    "note": "C4",
                    "duration": "whole"
                },
                "output_path": str(renders_dir / individual_name)
            }
            
            # Add parameters with both default and evolved values
            defaults = self.param_manager.get_default_parameters()
            all_params = {**defaults, **params}  # Evolved params override defaults
            
            # Simple mapping for common parameters
            param_name_mapping = {
                "1": "MasterVol",
                "2": "A Vol", 
                "3": "A Pan",
                "4": "A Octave",
                "5": "A Fine",
                "12": "12",  # Filter Cutoff (using ID as name)
                "16": "16",  # Filter Resonance
                "24": "24",  # Env Attack
                "32": "32",  # Env Sustain
            }
            
            for param_id, value in all_params.items():
                param_name = param_name_mapping.get(param_id, param_id)
                render_config["parameters"].append({
                    "track": "0",
                    "fx": "Serum",
                    "param": param_name,
                    "value": value
                })
            
            render_configs.append(render_config)
        
        return {
            "session_name": session_name,
            "render_configs": render_configs
        }
    
    def execute_session(self, session_dir: Path) -> Tuple[bool, List[Path]]:
        """
        Execute a complete session, rendering all individuals.
        
        Args:
            session_dir: Session directory containing renders structure
            
        Returns:
            Tuple of (success, list of rendered audio paths)
        """
        session_name = session_dir.name
        config_path = self.reaper_project_path / "session-configs" / f"{session_name}.json"
        
        if not config_path.exists():
            logger.error(f"Session config not found: {config_path}")
            return False, []
        
        logger.info(f"Executing batch session: {session_name}")
        
        try:
            # Change to REAPER project directory
            original_cwd = Path.cwd()
            reaper_cwd = self.reaper_project_path
            
            # Import REAPER execution system
            reaper_main_dir = Path(__file__).parent.parent / "reaper"
            import sys
            sys.path.append(str(reaper_main_dir))
            
            os.chdir(reaper_cwd)
            
            try:
                # Import the main REAPER execution function
                spec = importlib.util.spec_from_file_location("reaper_main", reaper_main_dir / "main.py")
                reaper_main = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(reaper_main)
                
                execute_reaper_with_session = reaper_main.execute_reaper_with_session
                
                # Execute REAPER session
                logger.info(f"Executing REAPER batch session: {config_path.name}")
                result = execute_reaper_with_session(config_path.name)
                
                if result.returncode == 0:
                    # Collect all rendered audio files
                    audio_paths = []
                    renders_dir = session_dir / "renders"
                    
                    for individual_dir in sorted(renders_dir.glob("individual_*")):
                        audio_file = individual_dir / "untitled.wav"
                        if audio_file.exists():
                            audio_paths.append(audio_file)
                            logger.info(f"Rendered audio: {audio_file}")
                        else:
                            logger.warning(f"Audio file not found: {audio_file}")
                    
                    # Try to collect artifacts using ArtifactManager, even if audio_paths is empty
                    # (REAPER creates files in different locations than expected)
                    if self.artifact_manager:
                        generation = self._extract_generation_from_session_dir(session_dir)
                        session_config_path = config_path
                        
                        # Use REAPER renders directory as source
                        reaper_renders_dir = self.reaper_project_path / "renders"
                        
                        num_collected, collected_paths = self.artifact_manager.collect_reaper_artifacts(
                            generation=generation,
                            reaper_renders_dir=reaper_renders_dir,
                            session_config_path=session_config_path
                        )
                        
                        logger.info(f"ArtifactManager collected {num_collected} artifacts for generation {generation}")
                        if collected_paths:
                            return True, collected_paths
                        elif audio_paths:
                            return True, audio_paths
                        else:
                            # Still return success if ArtifactManager found files even though original check failed
                            logger.info("No audio files found in expected locations, but ArtifactManager may have collected from REAPER renders")
                            return num_collected > 0, collected_paths
                    else:
                        # No artifact manager - check REAPER renders directory directly for files
                        reaper_renders_dir = self.reaper_project_path / "renders"
                        wav_files = list(reaper_renders_dir.glob("**/*.wav"))
                        
                        # Sort by modification time to get most recent files
                        wav_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                        
                        # Look for recently created files (within last 60 seconds)
                        import time
                        current_time = time.time()
                        recent_files = []
                        for wav_file in wav_files:
                            file_age = current_time - wav_file.stat().st_mtime
                            if file_age < 60:  # Recent file
                                recent_files.append(wav_file)
                        
                        if recent_files:
                            logger.info(f"Found {len(recent_files)} recent audio files in REAPER renders")
                            return True, recent_files
                        elif audio_paths:
                            return True, audio_paths
                    
                    logger.info(f"Session completed successfully: {len(audio_paths)} audio files rendered")
                    return True, audio_paths
                    
                else:
                    logger.error(f"REAPER execution failed with return code: {result.returncode}")
                    return False, []
                    
            finally:
                os.chdir(original_cwd)
                
        except Exception as e:
            logger.error(f"Error executing session: {e}")
            return False, []
    
    def get_target_audio(self) -> Optional[Path]:
        """
        Get target audio file for the experiment.
        
        Returns:
            Path to target audio or None if not found
        """
        return self.target_audio_path
    
    def get_individual_audio(self, session_dir: Path, individual_index: int) -> Optional[Path]:
        """
        Get audio file for a specific individual.
        
        Args:
            session_dir: Session directory
            individual_index: Index of individual (0-based)
            
        Returns:
            Path to individual audio or None if not found
        """
        audio_path = session_dir / "renders" / f"individual_{individual_index:03d}" / "untitled.wav"
        return audio_path if audio_path.exists() else None
    
    def list_session_audio_files(self, session_dir: Path) -> Dict[str, Path]:
        """
        List all audio files in a session with labels.
        
        Args:
            session_dir: Session directory
            
        Returns:
            Dictionary mapping labels to audio file paths
        """
        audio_files = {}
        
        # Target audio (from experiment level)
        target_audio = self.get_target_audio()
        if target_audio:
            audio_files["target"] = target_audio
        
        # Individual audio files
        renders_dir = session_dir / "renders"
        if renders_dir.exists():
            for individual_dir in sorted(renders_dir.glob("individual_*")):
                individual_index = int(individual_dir.name.split('_')[1])
                audio_file = individual_dir / "untitled.wav"
                if audio_file.exists():
                    audio_files[f"individual_{individual_index:03d}"] = audio_file
        
        return audio_files
    
    def _extract_generation_from_session_dir(self, session_dir: Path) -> int:
        """
        Extract generation number from session directory name.
        
        Args:
            session_dir: Session directory with name like "generation_001"
            
        Returns:
            Generation number
        """
        try:
            # Parse generation number from directory name like "generation_001"
            generation_str = session_dir.name.split('_')[1]
            return int(generation_str)
        except (IndexError, ValueError):
            logger.warning(f"Could not extract generation from session dir: {session_dir.name}")
            return 1  # Default to generation 1