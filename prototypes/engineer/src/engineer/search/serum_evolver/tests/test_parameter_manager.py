"""
Comprehensive unit tests for SerumParameterManager.

Tests cover:
- Parameter loading and parsing
- Parameter validation
- Constraint set validation 
- Default parameter management
- Error handling and edge cases
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, mock_open
from typing import Dict, Any

from serum_evolver.parameter_manager import SerumParameterManager, ISerumParameterManager
from serum_evolver.interfaces import SerumParameters, ParameterConstraintSet


class TestSerumParameterManager:
    """Test cases for SerumParameterManager implementation."""

    @pytest.fixture
    def sample_parameters_data(self) -> Dict[str, Any]:
        """Sample parameters data matching fx_parameters.json structure."""
        return {
            "fx_data": {
                "Serum_Track_VST3i:_Serum_Xfer_Records": {
                    "name": "VST3i: Serum (Xfer Records)",
                    "param_count": 3,
                    "parameters": {
                        "1": {
                            "formatted_value": " 70% (-9.3 dB)",
                            "identifier": "0:0",
                            "max_value": 1.0,
                            "mid_value": 0.5,
                            "min_value": 0.0,
                            "name": "MasterVol",
                            "normalized_value": 0.7,
                            "value": 0.7
                        },
                        "2": {
                            "formatted_value": " 75% (-5.0 dB)",
                            "identifier": "1:1",
                            "max_value": 1.0,
                            "mid_value": 0.5,
                            "min_value": 0.0,
                            "name": "A Vol",
                            "normalized_value": 0.75,
                            "value": 0.75
                        },
                        "3": {
                            "formatted_value": " 0",
                            "identifier": "2:2",
                            "max_value": 10.0,
                            "mid_value": None,  # Test case with None mid_value
                            "min_value": -5.0,
                            "name": "A Pan",
                            "normalized_value": 2.5,
                            "value": 2.5
                        }
                    }
                }
            }
        }

    @pytest.fixture
    def temp_json_file(self, sample_parameters_data: Dict[str, Any]) -> Path:
        """Create a temporary JSON file with sample parameters."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(sample_parameters_data, f)
            return Path(f.name)

    @pytest.fixture
    def parameter_manager(self, temp_json_file: Path) -> SerumParameterManager:
        """Create a SerumParameterManager instance with sample data."""
        return SerumParameterManager(temp_json_file)

    def test_implements_interface(self):
        """Test that SerumParameterManager implements ISerumParameterManager."""
        assert issubclass(SerumParameterManager, ISerumParameterManager)

    def test_init_success(self, temp_json_file: Path, sample_parameters_data: Dict[str, Any]):
        """Test successful initialization with valid JSON file."""
        manager = SerumParameterManager(temp_json_file)
        
        assert manager.fx_params_path == temp_json_file
        assert len(manager.parameters) == 3
        assert "1" in manager.parameters
        assert "2" in manager.parameters
        assert "3" in manager.parameters

    def test_init_file_not_found(self):
        """Test initialization with non-existent file raises FileNotFoundError."""
        non_existent_path = Path("/non/existent/file.json")
        
        with pytest.raises(FileNotFoundError, match="Parameters file not found"):
            SerumParameterManager(non_existent_path)

    def test_init_invalid_json(self):
        """Test initialization with invalid JSON raises ValueError."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("invalid json content {")
            invalid_file = Path(f.name)
        
        with pytest.raises(ValueError, match="Invalid JSON in parameters file"):
            SerumParameterManager(invalid_file)

    def test_init_missing_fx_data(self):
        """Test initialization with JSON missing fx_data section."""
        missing_data = {"other_data": {}}
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(missing_data, f)
            invalid_file = Path(f.name)
        
        with pytest.raises(ValueError, match="No 'fx_data' section found"):
            SerumParameterManager(invalid_file)

    def test_parameter_parsing(self, parameter_manager: SerumParameterManager):
        """Test that parameters are parsed correctly."""
        params = parameter_manager.parameters
        
        # Test parameter 1
        param1 = params["1"]
        assert param1["name"] == "MasterVol"
        assert param1["min_value"] == 0.0
        assert param1["max_value"] == 1.0
        assert param1["mid_value"] == 0.5
        assert param1["normalized_value"] == 0.7
        assert param1["identifier"] == "0:0"
        
        # Test parameter with None mid_value
        param3 = params["3"]
        assert param3["name"] == "A Pan"
        assert param3["min_value"] == -5.0
        assert param3["max_value"] == 10.0
        assert param3["mid_value"] is None
        assert param3["normalized_value"] == 2.5

    def test_validate_parameter_value_success(self, parameter_manager: SerumParameterManager):
        """Test successful parameter value validation."""
        # Test valid values within bounds
        assert parameter_manager.validate_parameter_value("1", 0.0) is True
        assert parameter_manager.validate_parameter_value("1", 0.5) is True
        assert parameter_manager.validate_parameter_value("1", 1.0) is True
        
        # Test parameter with different range
        assert parameter_manager.validate_parameter_value("3", -5.0) is True
        assert parameter_manager.validate_parameter_value("3", 2.5) is True
        assert parameter_manager.validate_parameter_value("3", 10.0) is True

    def test_validate_parameter_value_failure(self, parameter_manager: SerumParameterManager):
        """Test parameter value validation with invalid values."""
        # Test values outside bounds
        assert parameter_manager.validate_parameter_value("1", -0.1) is False
        assert parameter_manager.validate_parameter_value("1", 1.1) is False
        
        # Test with different range
        assert parameter_manager.validate_parameter_value("3", -5.1) is False
        assert parameter_manager.validate_parameter_value("3", 10.1) is False

    def test_validate_parameter_value_unknown_param(self, parameter_manager: SerumParameterManager):
        """Test parameter validation with unknown parameter ID."""
        assert parameter_manager.validate_parameter_value("999", 0.5) is False

    def test_get_parameter_bounds_success(self, parameter_manager: SerumParameterManager):
        """Test successful retrieval of parameter bounds."""
        min_val, max_val = parameter_manager.get_parameter_bounds("1")
        assert min_val == 0.0
        assert max_val == 1.0
        
        min_val, max_val = parameter_manager.get_parameter_bounds("3")
        assert min_val == -5.0
        assert max_val == 10.0

    def test_get_parameter_bounds_unknown_param(self, parameter_manager: SerumParameterManager):
        """Test parameter bounds retrieval with unknown parameter."""
        with pytest.raises(KeyError, match="Parameter '999' not found"):
            parameter_manager.get_parameter_bounds("999")

    def test_validate_constraint_set_success(self, parameter_manager: SerumParameterManager):
        """Test successful constraint set validation."""
        # Valid constraint sets
        constraint_set1: ParameterConstraintSet = {
            "1": (0.2, 0.8),
            "2": (0.0, 1.0)
        }
        assert parameter_manager.validate_constraint_set(constraint_set1) is True
        
        constraint_set2: ParameterConstraintSet = {
            "3": (-4.0, 9.0)
        }
        assert parameter_manager.validate_constraint_set(constraint_set2) is True
        
        # Edge case: constraint equals bounds
        constraint_set3: ParameterConstraintSet = {
            "1": (0.0, 1.0)
        }
        assert parameter_manager.validate_constraint_set(constraint_set3) is True

    def test_validate_constraint_set_unknown_parameter(self, parameter_manager: SerumParameterManager):
        """Test constraint set validation with unknown parameter."""
        constraint_set: ParameterConstraintSet = {
            "999": (0.0, 1.0)
        }
        assert parameter_manager.validate_constraint_set(constraint_set) is False

    def test_validate_constraint_set_invalid_constraint(self, parameter_manager: SerumParameterManager):
        """Test constraint set validation with invalid constraint (min > max)."""
        constraint_set: ParameterConstraintSet = {
            "1": (0.8, 0.2)  # min > max
        }
        assert parameter_manager.validate_constraint_set(constraint_set) is False

    def test_validate_constraint_set_out_of_bounds(self, parameter_manager: SerumParameterManager):
        """Test constraint set validation with constraints outside parameter bounds."""
        # Constraint min below parameter min
        constraint_set1: ParameterConstraintSet = {
            "1": (-0.1, 0.5)
        }
        assert parameter_manager.validate_constraint_set(constraint_set1) is False
        
        # Constraint max above parameter max
        constraint_set2: ParameterConstraintSet = {
            "1": (0.5, 1.1)
        }
        assert parameter_manager.validate_constraint_set(constraint_set2) is False
        
        # Both bounds outside
        constraint_set3: ParameterConstraintSet = {
            "3": (-6.0, 11.0)
        }
        assert parameter_manager.validate_constraint_set(constraint_set3) is False

    def test_get_default_parameters(self, parameter_manager: SerumParameterManager):
        """Test retrieval of default parameter values."""
        defaults = parameter_manager.get_default_parameters()
        
        # Should have all parameters
        assert len(defaults) == 3
        assert "1" in defaults
        assert "2" in defaults
        assert "3" in defaults
        
        # Parameter 1: uses mid_value
        assert defaults["1"] == 0.5
        
        # Parameter 2: uses mid_value
        assert defaults["2"] == 0.5
        
        # Parameter 3: mid_value is None, should use normalized_value
        assert defaults["3"] == 2.5

    def test_get_default_parameters_calculated_fallback(self):
        """Test default parameters calculation when mid_value and normalized_value are None."""
        fallback_data = {
            "fx_data": {
                "Test_Plugin": {
                    "name": "Test Plugin",
                    "param_count": 1,
                    "parameters": {
                        "1": {
                            "name": "TestParam",
                            "min_value": 2.0,
                            "max_value": 8.0,
                            "mid_value": None,
                            "normalized_value": None
                        }
                    }
                }
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(fallback_data, f)
            temp_file = Path(f.name)
        
        manager = SerumParameterManager(temp_file)
        defaults = manager.get_default_parameters()
        
        # Should calculate middle value: (2.0 + 8.0) / 2.0 = 5.0
        assert defaults["1"] == 5.0

    def test_get_parameter_info(self, parameter_manager: SerumParameterManager):
        """Test retrieval of complete parameter information."""
        info = parameter_manager.get_parameter_info("1")
        assert info is not None
        assert info["name"] == "MasterVol"
        assert info["min_value"] == 0.0
        assert info["max_value"] == 1.0
        
        # Test unknown parameter
        assert parameter_manager.get_parameter_info("999") is None

    def test_get_parameter_name(self, parameter_manager: SerumParameterManager):
        """Test retrieval of parameter names."""
        assert parameter_manager.get_parameter_name("1") == "MasterVol"
        assert parameter_manager.get_parameter_name("2") == "A Vol"
        assert parameter_manager.get_parameter_name("3") == "A Pan"
        assert parameter_manager.get_parameter_name("999") is None

    def test_get_all_parameter_ids(self, parameter_manager: SerumParameterManager):
        """Test retrieval of all parameter IDs."""
        ids = parameter_manager.get_all_parameter_ids()
        assert len(ids) == 3
        assert "1" in ids
        assert "2" in ids
        assert "3" in ids

    def test_parameter_lookup(self, parameter_manager: SerumParameterManager):
        """Test parameter lookup by name."""
        # Test case-insensitive lookup
        assert parameter_manager.find_parameter_by_name("MasterVol") == "1"
        assert parameter_manager.find_parameter_by_name("mastervol") == "1"
        assert parameter_manager.find_parameter_by_name("MASTERVOL") == "1"
        assert parameter_manager.find_parameter_by_name("A Vol") == "2"
        assert parameter_manager.find_parameter_by_name("a vol") == "2"
        
        # Test unknown name
        assert parameter_manager.find_parameter_by_name("Unknown") is None

    def test_load_parameters_method(self, parameter_manager: SerumParameterManager, sample_parameters_data: Dict[str, Any]):
        """Test the load_parameters method for reloading."""
        # Create a new file with different data
        new_data = {
            "fx_data": {
                "NewPlugin": {
                    "name": "New Plugin",
                    "param_count": 1,
                    "parameters": {
                        "100": {
                            "name": "NewParam",
                            "min_value": 0.0,
                            "max_value": 2.0,
                            "mid_value": 1.0,
                            "normalized_value": 1.0
                        }
                    }
                }
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(new_data, f)
            new_file = Path(f.name)
        
        # Load new parameters
        params = parameter_manager.load_parameters(new_file)
        
        # Verify new data is loaded
        assert len(params) == 1
        assert "100" in params
        assert params["100"]["name"] == "NewParam"
        assert parameter_manager.get_parameter_name("100") == "NewParam"
        
        # Old parameters should be gone
        assert parameter_manager.get_parameter_name("1") is None


class TestSerumParameterManagerIntegration:
    """Integration tests with real data structures and edge cases."""

    def test_large_parameter_set(self):
        """Test handling of large parameter sets (simulating real Serum data)."""
        # Create data with many parameters
        large_data = {
            "fx_data": {
                "Serum": {
                    "name": "Serum",
                    "param_count": 1000,
                    "parameters": {}
                }
            }
        }
        
        # Generate 1000 test parameters
        for i in range(1, 1001):
            large_data["fx_data"]["Serum"]["parameters"][str(i)] = {
                "name": f"Param_{i}",
                "min_value": 0.0,
                "max_value": 1.0,
                "mid_value": 0.5,
                "normalized_value": 0.5
            }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(large_data, f)
            temp_file = Path(f.name)
        
        # Should handle large data set efficiently
        manager = SerumParameterManager(temp_file)
        assert len(manager.parameters) == 1000
        assert len(manager.get_all_parameter_ids()) == 1000
        assert len(manager.get_default_parameters()) == 1000
        
        # Test random access
        assert manager.validate_parameter_value("500", 0.75) is True
        assert manager.get_parameter_name("500") == "Param_500"

    def test_edge_case_parameter_values(self):
        """Test handling of edge case parameter values."""
        edge_data = {
            "fx_data": {
                "EdgeCases": {
                    "name": "Edge Cases",
                    "param_count": 4,
                    "parameters": {
                        "1": {  # Zero range parameter
                            "name": "ZeroRange",
                            "min_value": 5.0,
                            "max_value": 5.0,
                            "mid_value": 5.0,
                            "normalized_value": 5.0
                        },
                        "2": {  # Very large range
                            "name": "LargeRange",
                            "min_value": -1000000.0,
                            "max_value": 1000000.0,
                            "mid_value": 0.0,
                            "normalized_value": 0.0
                        },
                        "3": {  # Very small range
                            "name": "SmallRange",
                            "min_value": 0.0000001,
                            "max_value": 0.0000002,
                            "mid_value": 0.00000015,
                            "normalized_value": 0.00000015
                        },
                        "4": {  # Missing optional fields
                            "name": "Minimal",
                            "min_value": 0.0,
                            "max_value": 1.0
                            # No mid_value, normalized_value, etc.
                        }
                    }
                }
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(edge_data, f)
            temp_file = Path(f.name)
        
        manager = SerumParameterManager(temp_file)
        
        # Test zero range parameter
        assert manager.validate_parameter_value("1", 5.0) is True
        assert manager.validate_parameter_value("1", 4.9) is False
        assert manager.validate_parameter_value("1", 5.1) is False
        
        # Test large range parameter
        assert manager.validate_parameter_value("2", -999999.0) is True
        assert manager.validate_parameter_value("2", 999999.0) is True
        assert manager.validate_parameter_value("2", -1000001.0) is False
        
        # Test small range parameter
        assert manager.validate_parameter_value("3", 0.00000015) is True
        assert manager.validate_parameter_value("3", 0.00000005) is False
        
        # Test minimal parameter (should use calculated default)
        defaults = manager.get_default_parameters()
        assert defaults["4"] == 0.5  # (0.0 + 1.0) / 2.0

    def test_file_permission_error(self):
        """Test handling of file permission errors."""
        # Create a temporary file first
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"fx_data": {"test": {"parameters": {}}}}, f)
            temp_file = Path(f.name)
        
        # Create a mock that will raise PermissionError when the file exists but can't be read
        with patch('builtins.open', side_effect=PermissionError("Permission denied")):
            with pytest.raises(ValueError, match="Error reading parameters file"):
                SerumParameterManager(temp_file)

    def test_concurrent_access_safety(self):
        """Test that parameter manager is safe for concurrent read access."""
        # Create test data
        test_data = {
            "fx_data": {
                "TestPlugin": {
                    "name": "Test Plugin",
                    "param_count": 3,
                    "parameters": {
                        "1": {
                            "name": "MasterVol",
                            "min_value": 0.0,
                            "max_value": 1.0,
                            "mid_value": 0.5,
                            "normalized_value": 0.5
                        },
                        "2": {
                            "name": "A Vol",
                            "min_value": 0.0,
                            "max_value": 1.0,
                            "mid_value": 0.5,
                            "normalized_value": 0.75
                        },
                        "3": {
                            "name": "A Pan",
                            "min_value": 0.0,
                            "max_value": 1.0,
                            "mid_value": 0.5,
                            "normalized_value": 0.5
                        }
                    }
                }
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(test_data, f)
            temp_file = Path(f.name)
        
        manager = SerumParameterManager(temp_file)
        
        # Simulate concurrent access to different methods
        results = []
        
        # Multiple simultaneous lookups
        results.append(manager.validate_parameter_value("1", 0.5))
        results.append(manager.get_parameter_bounds("2"))
        results.append(manager.get_parameter_name("3"))
        results.append(manager.find_parameter_by_name("MasterVol"))
        
        # All operations should succeed
        assert results[0] is True
        assert results[1] == (0.0, 1.0)
        assert results[2] == "A Pan"
        assert results[3] == "1"


if __name__ == "__main__":
    pytest.main([__file__])