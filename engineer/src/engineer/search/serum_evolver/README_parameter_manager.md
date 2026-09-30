# SerumParameterManager

A comprehensive parameter management system for the Serum VST plugin, part of the SerumEvolver multi-agent system.

## Overview

The `SerumParameterManager` class provides a robust interface for loading, validating, and managing Serum VST plugin parameters. It supports all ~2400 Serum parameters with proper bounds checking, constraint validation, and efficient parameter lookup.

## Features

- **Parameter Loading**: Load and parse `fx_parameters.json` files containing Serum parameter definitions
- **Validation**: Validate parameter values against defined min/max bounds
- **Constraint Sets**: Validate parameter constraint sets for genetic algorithm bounds
- **Default Values**: Generate appropriate default parameter values
- **Parameter Lookup**: Find parameters by name (case-insensitive) or ID
- **Error Handling**: Comprehensive error handling for file I/O and data validation
- **Performance**: Efficient lookup tables for fast parameter access

## Key Classes

### SerumParameterManager

Main implementation class that inherits from `ISerumParameterManager`.

#### Initialization

```python
from pathlib import Path
from serum_evolver.parameter_manager import SerumParameterManager

# Initialize with fx_parameters.json file
fx_params_path = Path("reaper/fx_parameters.json")
manager = SerumParameterManager(fx_params_path)
```

#### Core Methods

- `validate_parameter_value(param_id: str, value: float) -> bool`: Validate a parameter value
- `get_parameter_bounds(param_id: str) -> Tuple[float, float]`: Get min/max bounds
- `validate_constraint_set(constraint_set: ParameterConstraintSet) -> bool`: Validate constraints
- `get_default_parameters() -> SerumParameters`: Get default parameter values
- `get_parameter_info(param_id: str) -> Optional[Dict[str, Any]]`: Get complete parameter info
- `find_parameter_by_name(name: str) -> Optional[str]`: Find parameter ID by name

## Usage Examples

### Basic Parameter Validation

```python
# Validate parameter values
is_valid = manager.validate_parameter_value("1", 0.5)  # MasterVol
print(f"Value 0.5 is valid: {is_valid}")  # True

# Get parameter bounds
min_val, max_val = manager.get_parameter_bounds("1")
print(f"MasterVol bounds: [{min_val}, {max_val}]")  # [0.0, 1.0]
```

### Constraint Set Validation

```python
from serum_evolver.interfaces import ParameterConstraintSet

# Define constraints for genetic algorithm
constraints: ParameterConstraintSet = {
    "1": (0.2, 0.8),    # MasterVol between 20%-80%
    "2": (0.0, 1.0),    # A Vol full range
    "3": (0.4, 0.6)     # A Pan centered
}

# Validate constraints are within parameter bounds
is_valid = manager.validate_constraint_set(constraints)
print(f"Constraint set valid: {is_valid}")
```

### Parameter Lookup

```python
# Find parameter by name
param_id = manager.find_parameter_by_name("MasterVol")
print(f"MasterVol ID: {param_id}")  # "1"

# Get parameter information
info = manager.get_parameter_info("1")
print(f"Parameter info: {info['name']} [{info['min_value']}, {info['max_value']}]")
```

### Default Parameters

```python
# Get all default parameter values
defaults = manager.get_default_parameters()
print(f"Loaded {len(defaults)} default parameters")

# Use defaults as starting point for genetic algorithm
initial_parameters = defaults.copy()
```

## Testing

Comprehensive unit tests are provided in `tests/test_parameter_manager.py`:

```bash
# Run tests
python -m pytest serum_evolver/tests/test_parameter_manager.py -v

# Run with coverage
python -m pytest serum_evolver/tests/test_parameter_manager.py --cov=serum_evolver.parameter_manager
```

Test coverage includes:
- Parameter loading and parsing
- Value validation with edge cases
- Constraint set validation
- Default parameter generation
- Error handling and file I/O
- Large dataset performance
- Concurrent access safety

## File Format

The system expects `fx_parameters.json` files in this format:

```json
{
  "fx_data": {
    "Serum_Track_VST3i:_Serum_Xfer_Records": {
      "name": "VST3i: Serum (Xfer Records)",
      "param_count": 2400,
      "parameters": {
        "1": {
          "name": "MasterVol",
          "min_value": 0.0,
          "max_value": 1.0,
          "mid_value": 0.5,
          "normalized_value": 0.7,
          "identifier": "0:0",
          "formatted_value": " 70% (-9.3 dB)"
        }
      }
    }
  }
}
```

## Error Handling

The system provides robust error handling:

- `FileNotFoundError`: When parameter file doesn't exist
- `ValueError`: For malformed JSON or missing required data
- `KeyError`: When requesting unknown parameter IDs
- Graceful degradation for missing optional fields

## Performance

- Optimized for large parameter sets (tested with 2400+ parameters)
- Efficient parameter lookup with O(1) name-to-ID mapping
- Memory-efficient parameter storage
- Fast constraint set validation

## Integration

This parameter manager integrates with other SerumEvolver components:

- **GA Engine**: Validates parameter bounds for genetic algorithms
- **Audio Generator**: Ensures parameter values are valid before audio generation  
- **Feature Extractor**: Works with parameter-based audio analysis

## See Also

- `examples/parameter_manager_usage.py` - Complete usage examples
- `interfaces.py` - Type definitions and interfaces
- `tests/test_parameter_manager.py` - Comprehensive test suite