"""
Smoke test for SerumAudioGenerator integration with existing REAPER infrastructure.
"""

import pytest
from pathlib import Path
from serum_evolver.audio_generator import SerumAudioGenerator
from serum_evolver.parameter_manager import SerumParameterManager


class TestAudioGeneratorIntegration:
    """Test integration with actual system components."""
    
    def test_can_initialize_with_real_components(self):
        """Test that we can initialize with real project paths."""
        # Use the actual REAPER project path
        reaper_path = Path(__file__).parent.parent.parent / "reaper"
        fx_params_path = reaper_path / "fx_parameters.json"
        
        # Check if the files exist (skip if not in proper environment)
        if not reaper_path.exists() or not fx_params_path.exists():
            pytest.skip("REAPER project directory or fx_parameters.json not found")
        
        # Initialize parameter manager
        param_manager = SerumParameterManager(fx_params_path)
        
        # Initialize audio generator
        audio_generator = SerumAudioGenerator(reaper_path, param_manager)
        
        # Basic functionality checks
        assert audio_generator.reaper_project_path == reaper_path
        assert audio_generator.param_manager == param_manager
        
        # Test parameter generation
        constraint_set = {"4": (0.2, 0.8)}  # A Octave parameter
        random_params = audio_generator._generate_random_parameters(constraint_set)
        
        assert "4" in random_params
        assert 0.2 <= random_params["4"] <= 0.8
        
        # Test parameter validation
        assert param_manager.validate_parameter_value("4", 0.5)
        assert not param_manager.validate_parameter_value("4", 2.0)
        
        print("✓ Integration smoke test passed")
    
    def test_session_config_structure_matches_existing(self):
        """Test that generated session configs match the expected structure."""
        reaper_path = Path(__file__).parent.parent.parent / "reaper"
        fx_params_path = reaper_path / "fx_parameters.json"
        
        if not reaper_path.exists() or not fx_params_path.exists():
            pytest.skip("REAPER project directory or fx_parameters.json not found")
        
        param_manager = SerumParameterManager(fx_params_path)
        audio_generator = SerumAudioGenerator(reaper_path, param_manager)
        
        # Create a session config
        session_name = "test_structure"
        serum_params = {"1": 0.75, "4": 0.5}
        
        config_path = audio_generator.reaper_session_manager.create_session_config(
            session_name, serum_params
        )
        
        assert config_path.exists()
        
        # Load and verify structure
        import json
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        # Check required fields
        assert "session_name" in config
        assert "render_configs" in config
        assert len(config["render_configs"]) == 1
        
        render_config = config["render_configs"][0]
        assert "render_id" in render_config
        assert "tracks" in render_config
        assert "parameters" in render_config
        assert "midi_files" in render_config
        assert "render_options" in render_config
        
        # Check render options
        render_options = render_config["render_options"]
        assert render_options["bpm"] == 148
        assert render_options["note"] == "C4"
        assert render_options["duration"] == "whole"
        
        # Cleanup
        config_path.unlink()
        
        print("✓ Session config structure test passed")
    
    def test_parameter_name_mapping(self):
        """Test parameter ID to name mapping."""
        reaper_path = Path(__file__).parent.parent.parent / "reaper"
        fx_params_path = reaper_path / "fx_parameters.json"
        
        if not reaper_path.exists() or not fx_params_path.exists():
            pytest.skip("REAPER project directory or fx_parameters.json not found")
        
        param_manager = SerumParameterManager(fx_params_path)
        audio_generator = SerumAudioGenerator(reaper_path, param_manager)
        
        session_manager = audio_generator.reaper_session_manager
        
        # Test known parameter mappings
        assert session_manager._get_param_name_from_id("1") == "MasterVol"
        assert session_manager._get_param_name_from_id("4") == "A Octave"
        assert session_manager._get_param_name_from_id("5") == "A Fine"
        
        print("✓ Parameter mapping test passed")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])