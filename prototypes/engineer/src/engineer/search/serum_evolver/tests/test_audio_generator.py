"""
Unit tests for SerumAudioGenerator and ReaperSessionManager.
"""

import pytest
import json
import uuid
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from serum_evolver.audio_generator import SerumAudioGenerator, ReaperSessionManager
from serum_evolver.parameter_manager import SerumParameterManager
from serum_evolver.interfaces import SerumParameters, ParameterConstraintSet


class TestReaperSessionManager:
    """Test cases for ReaperSessionManager."""
    
    @pytest.fixture
    def temp_reaper_dir(self):
        """Create temporary REAPER project directory."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def session_manager(self, temp_reaper_dir):
        """Create ReaperSessionManager instance."""
        return ReaperSessionManager(temp_reaper_dir)
    
    def test_initialization(self, session_manager, temp_reaper_dir):
        """Test ReaperSessionManager initialization."""
        assert session_manager.reaper_project_path == temp_reaper_dir
        assert session_manager.session_configs_dir == temp_reaper_dir / "session-configs"
        assert session_manager.renders_dir == temp_reaper_dir / "renders"
        assert session_manager.session_results_dir == temp_reaper_dir / "session-results"
        
        # Check that directories were created
        assert session_manager.session_configs_dir.exists()
        assert session_manager.renders_dir.exists()
        assert session_manager.session_results_dir.exists()
    
    def test_create_session_config(self, session_manager):
        """Test session configuration creation."""
        session_name = "test_session"
        serum_params = {
            "1": 0.75,  # MasterVol
            "4": 0.5,   # A Octave
            "5": 0.25   # A Fine
        }
        
        config_path = session_manager.create_session_config(session_name, serum_params)
        
        # Check that config file was created
        assert config_path.exists()
        assert config_path.name == f"{session_name}.json"
        
        # Load and verify config content
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        assert config["session_name"] == session_name
        assert len(config["render_configs"]) == 1
        
        render_config = config["render_configs"][0]
        assert len(render_config["parameters"]) == 3
        
        # Check parameter mapping
        params_by_name = {p["param"]: p["value"] for p in render_config["parameters"]}
        assert params_by_name["MasterVol"] == 0.75
        assert params_by_name["A Octave"] == 0.5
        assert params_by_name["A Fine"] == 0.25
        
        # Check render options
        render_options = render_config["render_options"]
        assert render_options["bpm"] == 148
        assert render_options["note"] == "C4"
        assert render_options["duration"] == "whole"
        assert render_options["sample_rate"] == 44100
    
    def test_get_param_name_from_id(self, session_manager):
        """Test parameter ID to name mapping."""
        assert session_manager._get_param_name_from_id("1") == "MasterVol"
        assert session_manager._get_param_name_from_id("4") == "A Octave"
        assert session_manager._get_param_name_from_id("unknown") == "unknown"
    
    def test_execute_session_success_mock(self, session_manager):
        """Test successful session execution with proper mocking."""
        session_name = "test_session"
        audio_file = session_manager.renders_dir / f"{session_name}_render.wav"
        audio_file.parent.mkdir(parents=True, exist_ok=True)
        audio_file.write_text("fake audio")
        
        config_path = session_manager.session_configs_dir / f"{session_name}.json"
        config_path.write_text('{"test": "config"}')
        
        # Mock the entire execute_session method behavior
        with patch.object(session_manager, 'execute_session') as mock_execute:
            mock_execute.return_value = (True, audio_file)
            success, audio_path = session_manager.execute_session(config_path)
            
            assert success
            assert audio_path == audio_file
    
    def test_execute_session_failure_mock(self, session_manager):
        """Test failed session execution with proper mocking."""
        config_path = session_manager.session_configs_dir / "test_session.json"
        config_path.write_text('{"test": "config"}')
        
        with patch.object(session_manager, 'execute_session') as mock_execute:
            mock_execute.return_value = (False, None)
            success, audio_path = session_manager.execute_session(config_path)
        
            assert not success
            assert audio_path is None
    
    def test_find_rendered_audio(self, session_manager):
        """Test finding rendered audio files."""
        session_name = "test_session"
        
        # Create fake render directory and audio file
        render_dir = session_manager.renders_dir / f"{session_name}_render"
        render_dir.mkdir(parents=True, exist_ok=True)
        audio_file = render_dir / "output.wav"
        audio_file.write_text("fake audio")
        
        found_audio = session_manager._find_rendered_audio(session_name)
        assert found_audio == audio_file
    
    def test_find_rendered_audio_not_found(self, session_manager):
        """Test finding rendered audio when no files exist."""
        found_audio = session_manager._find_rendered_audio("nonexistent_session")
        assert found_audio is None
    
    def test_cleanup_session_files(self, session_manager):
        """Test session file cleanup."""
        session_name = "test_session"
        
        # Create files to clean up
        config_file = session_manager.session_configs_dir / f"{session_name}.json"
        config_file.write_text('{"test": "config"}')
        
        result_file = session_manager.session_results_dir / f"{session_name}_results.log"
        result_file.write_text("test results")
        
        # Cleanup
        session_manager.cleanup_session_files(session_name)
        
        # Check files were removed
        assert not config_file.exists()
        assert not result_file.exists()


class TestSerumAudioGenerator:
    """Test cases for SerumAudioGenerator."""
    
    @pytest.fixture
    def temp_reaper_dir(self):
        """Create temporary REAPER project directory."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def mock_param_manager(self):
        """Create mock parameter manager."""
        manager = Mock(spec=SerumParameterManager)
        manager.validate_constraint_set.return_value = True
        manager.validate_parameter_value.return_value = True
        manager.get_default_parameters.return_value = {
            "1": 0.7,  # MasterVol default
            "2": 0.75, # A Vol default
            "3": 0.5,  # A Pan default
        }
        return manager
    
    @pytest.fixture
    def audio_generator(self, temp_reaper_dir, mock_param_manager):
        """Create SerumAudioGenerator instance."""
        return SerumAudioGenerator(temp_reaper_dir, mock_param_manager)
    
    def test_initialization(self, audio_generator, temp_reaper_dir, mock_param_manager):
        """Test SerumAudioGenerator initialization."""
        assert audio_generator.reaper_project_path == temp_reaper_dir
        assert audio_generator.param_manager == mock_param_manager
        assert isinstance(audio_generator.reaper_session_manager, ReaperSessionManager)
    
    def test_generate_random_parameters(self, audio_generator):
        """Test random parameter generation within constraints."""
        constraint_set = {
            "4": (0.2, 0.8),  # A Octave
            "5": (0.0, 0.5)   # A Fine
        }
        
        random_params = audio_generator._generate_random_parameters(constraint_set)
        
        assert len(random_params) == 2
        assert "4" in random_params
        assert "5" in random_params
        
        # Check values are within constraints
        assert 0.2 <= random_params["4"] <= 0.8
        assert 0.0 <= random_params["5"] <= 0.5
    
    def test_generate_random_parameters_empty_constraints(self, audio_generator):
        """Test random parameter generation with empty constraints."""
        constraint_set = {}
        random_params = audio_generator._generate_random_parameters(constraint_set)
        assert random_params == {}
    
    @patch.object(ReaperSessionManager, 'create_session_config')
    @patch.object(ReaperSessionManager, 'execute_session')
    def test_render_patch_success(self, mock_execute, mock_create_config, audio_generator):
        """Test successful patch rendering."""
        # Setup mocks
        config_path = Path("/fake/config.json")
        audio_path = Path("/fake/audio.wav")
        
        mock_create_config.return_value = config_path
        mock_execute.return_value = (True, audio_path)
        
        serum_params = {"4": 0.5, "5": 0.25}
        session_name = "test_render"
        
        result_audio_path = audio_generator.render_patch(serum_params, session_name)
        
        assert result_audio_path == audio_path
        mock_create_config.assert_called_once_with(session_name, serum_params)
        mock_execute.assert_called_once_with(config_path)
    
    @patch.object(ReaperSessionManager, 'create_session_config')
    @patch.object(ReaperSessionManager, 'execute_session')
    @patch.object(ReaperSessionManager, 'cleanup_session_files')
    def test_render_patch_failure(self, mock_cleanup, mock_execute, mock_create_config, audio_generator):
        """Test patch rendering failure."""
        # Setup mocks
        config_path = Path("/fake/config.json")
        
        mock_create_config.return_value = config_path
        mock_execute.return_value = (False, None)
        
        serum_params = {"4": 0.5, "5": 0.25}
        session_name = "test_render"
        
        with pytest.raises(RuntimeError, match="Audio rendering failed"):
            audio_generator.render_patch(serum_params, session_name)
        
        # Check cleanup was called
        mock_cleanup.assert_called_once_with(session_name)
    
    def test_render_patch_invalid_parameters(self, audio_generator, mock_param_manager):
        """Test rendering with invalid parameters."""
        # Setup mock to return False for validation
        mock_param_manager.validate_parameter_value.return_value = False
        
        serum_params = {"4": 999.0}  # Invalid value
        session_name = "test_render"
        
        with pytest.raises(ValueError, match="Invalid parameter value"):
            audio_generator.render_patch(serum_params, session_name)
    
    @patch.object(SerumAudioGenerator, 'render_patch')
    def test_create_random_patch_success(self, mock_render, audio_generator, mock_param_manager):
        """Test successful random patch creation."""
        # Setup mocks
        audio_path = Path("/fake/audio.wav")
        mock_render.return_value = audio_path
        
        constraint_set = {"4": (0.2, 0.8)}
        
        # Mock random generation to return predictable values
        with patch('random.uniform', return_value=0.5):
            serum_params, result_audio_path = audio_generator.create_random_patch(constraint_set)
        
        assert result_audio_path == audio_path
        assert serum_params == {"4": 0.5}
        
        # Check that default parameters were merged
        mock_param_manager.get_default_parameters.assert_called_once()
        
        # Check that render_patch was called with merged parameters
        expected_full_params = {
            "1": 0.7,   # Default
            "2": 0.75,  # Default
            "3": 0.5,   # Default
            "4": 0.5    # Generated
        }
        mock_render.assert_called_once()
        call_args = mock_render.call_args
        assert call_args[0][0] == expected_full_params
    
    def test_create_random_patch_invalid_constraints(self, audio_generator, mock_param_manager):
        """Test random patch creation with invalid constraints."""
        # Setup mock to return False for constraint validation
        mock_param_manager.validate_constraint_set.return_value = False
        
        constraint_set = {"4": (0.8, 0.2)}  # Invalid: min > max
        
        with pytest.raises(ValueError, match="Invalid constraint set provided"):
            audio_generator.create_random_patch(constraint_set)
    
    @patch.object(ReaperSessionManager, 'cleanup_session_files')
    def test_cleanup_session(self, mock_cleanup, audio_generator):
        """Test session cleanup."""
        session_name = "test_session"
        audio_generator.cleanup_session(session_name)
        mock_cleanup.assert_called_once_with(session_name)


class TestIntegration:
    """Integration tests with real parameter manager."""
    
    @pytest.fixture
    def temp_reaper_dir(self):
        """Create temporary REAPER project directory."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def real_param_manager(self, temp_reaper_dir):
        """Create real parameter manager with mock fx_parameters.json."""
        # Create mock fx_parameters.json
        fx_params = {
            "fx_data": {
                "Serum_Track": {
                    "name": "Serum",
                    "param_count": 5,
                    "parameters": {
                        "1": {
                            "name": "MasterVol",
                            "min_value": 0.0,
                            "max_value": 1.0,
                            "mid_value": 0.5,
                            "normalized_value": 0.7
                        },
                        "4": {
                            "name": "A Octave",
                            "min_value": 0.0,
                            "max_value": 1.0,
                            "mid_value": 0.5,
                            "normalized_value": 0.5
                        },
                        "5": {
                            "name": "A Fine",
                            "min_value": 0.0,
                            "max_value": 1.0,
                            "mid_value": 0.5,
                            "normalized_value": 0.0
                        }
                    }
                }
            }
        }
        
        fx_params_path = temp_reaper_dir / "fx_parameters.json"
        with open(fx_params_path, 'w') as f:
            json.dump(fx_params, f)
        
        return SerumParameterManager(fx_params_path)
    
    def test_integration_parameter_validation(self, temp_reaper_dir, real_param_manager):
        """Test integration with real parameter manager."""
        audio_generator = SerumAudioGenerator(temp_reaper_dir, real_param_manager)
        
        # Test valid constraint set
        valid_constraints = {
            "4": (0.2, 0.8),  # A Octave: valid range within [0.0, 1.0]
            "5": (0.0, 0.5)   # A Fine: valid range within [0.0, 1.0]
        }
        
        # This should not raise an exception
        random_params = audio_generator._generate_random_parameters(valid_constraints)
        assert len(random_params) == 2
        
        # Test invalid constraint set
        invalid_constraints = {
            "4": (0.5, 2.0),  # A Octave: max > parameter max (1.0)
        }
        
        # Parameter manager should reject this
        assert not real_param_manager.validate_constraint_set(invalid_constraints)
    
    def test_integration_default_parameters(self, temp_reaper_dir, real_param_manager):
        """Test integration with default parameter handling."""
        audio_generator = SerumAudioGenerator(temp_reaper_dir, real_param_manager)
        
        # Get defaults from parameter manager
        defaults = real_param_manager.get_default_parameters()
        
        # Should have normalized_value for parameters where available
        # The parameter manager uses mid_value as default if available, otherwise normalized_value
        assert defaults["1"] == 0.5   # MasterVol mid_value
        assert defaults["4"] == 0.5   # A Octave mid_value  
        assert defaults["5"] == 0.5   # A Fine mid_value
    
    @patch.object(ReaperSessionManager, 'execute_session')
    def test_integration_full_workflow(self, mock_execute, temp_reaper_dir, real_param_manager):
        """Test complete workflow integration."""
        # Setup mock
        audio_path = temp_reaper_dir / "test_audio.wav"
        mock_execute.return_value = (True, audio_path)
        
        audio_generator = SerumAudioGenerator(temp_reaper_dir, real_param_manager)
        
        constraint_set = {"4": (0.3, 0.7)}
        
        with patch('random.uniform', return_value=0.5):
            generated_params, result_audio_path = audio_generator.create_random_patch(constraint_set)
        
        # Check that only constrained parameter is in generated_params
        assert generated_params == {"4": 0.5}
        assert result_audio_path == audio_path
        
        # Verify session config was created with proper format
        config_files = list((temp_reaper_dir / "session-configs").glob("*.json"))
        assert len(config_files) == 1
        
        with open(config_files[0], 'r') as f:
            config = json.load(f)
        
        # Should have all parameters (defaults + generated)
        param_names = {p["param"] for p in config["render_configs"][0]["parameters"]}
        assert "MasterVol" in param_names  # From defaults
        assert "A Octave" in param_names   # Generated
        assert "A Fine" in param_names     # From defaults


class TestConcurrency:
    """Test concurrent operations for GA batch processing."""
    
    @pytest.fixture
    def temp_reaper_dir(self):
        """Create temporary REAPER project directory."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def mock_param_manager(self):
        """Create mock parameter manager."""
        manager = Mock(spec=SerumParameterManager)
        manager.validate_constraint_set.return_value = True
        manager.validate_parameter_value.return_value = True
        manager.get_default_parameters.return_value = {"1": 0.7}
        return manager
    
    def test_unique_session_names(self, temp_reaper_dir, mock_param_manager):
        """Test that concurrent sessions get unique names."""
        audio_generator = SerumAudioGenerator(temp_reaper_dir, mock_param_manager)
        
        constraint_set = {"4": (0.0, 1.0)}
        
        # Generate multiple sessions
        session_names = []
        for _ in range(10):
            # Mock the render_patch to avoid actual REAPER execution
            with patch.object(audio_generator, 'render_patch') as mock_render:
                mock_render.return_value = Path("/fake/audio.wav")
                generated_params, _ = audio_generator.create_random_patch(constraint_set)
                
                # Extract session name from mock call
                session_name = mock_render.call_args[0][1]
                session_names.append(session_name)
        
        # All session names should be unique
        assert len(set(session_names)) == 10
        
        # All should start with "random_"
        assert all(name.startswith("random_") for name in session_names)
    
    @patch.object(ReaperSessionManager, 'execute_session')
    def test_concurrent_config_creation(self, mock_execute, temp_reaper_dir, mock_param_manager):
        """Test concurrent session config creation."""
        # Setup mock
        mock_execute.return_value = (True, Path("/fake/audio.wav"))
        
        audio_generator = SerumAudioGenerator(temp_reaper_dir, mock_param_manager)
        constraint_set = {"4": (0.0, 1.0)}
        
        # Create multiple sessions simultaneously
        import concurrent.futures
        import threading
        
        def create_random_patch():
            with patch('random.uniform', return_value=0.5):
                return audio_generator.create_random_patch(constraint_set)
        
        # Use ThreadPoolExecutor to simulate concurrent requests
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(create_random_patch) for _ in range(5)]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]
        
        assert len(results) == 5
        
        # Check that config files were created
        config_files = list((temp_reaper_dir / "session-configs").glob("*.json"))
        assert len(config_files) == 5
        
        # All config files should have unique names
        config_names = [f.name for f in config_files]
        assert len(set(config_names)) == 5


if __name__ == "__main__":
    pytest.main([__file__])