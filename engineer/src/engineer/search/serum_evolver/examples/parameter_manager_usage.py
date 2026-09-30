#!/usr/bin/env python3
"""
Example usage of SerumParameterManager.

This demonstrates how to use the parameter management system for 
working with Serum VST plugin parameters.
"""

from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from serum_evolver.parameter_manager import SerumParameterManager
from serum_evolver.interfaces import ParameterConstraintSet


def main():
    """Demonstrate SerumParameterManager usage."""
    
    # Path to fx_parameters.json (adjust as needed)
    fx_params_path = Path(__file__).parent.parent.parent / "reaper" / "fx_parameters.json"
    
    if not fx_params_path.exists():
        print(f"Error: fx_parameters.json not found at {fx_params_path}")
        return
    
    # Initialize the parameter manager
    print("Loading Serum parameters...")
    manager = SerumParameterManager(fx_params_path)
    print(f"✓ Loaded {len(manager.parameters)} parameters")
    
    # Example 1: Get parameter information
    print("\n=== Parameter Information ===")
    param_ids = manager.get_all_parameter_ids()[:5]  # First 5 parameters
    
    for param_id in param_ids:
        name = manager.get_parameter_name(param_id)
        bounds = manager.get_parameter_bounds(param_id)
        info = manager.get_parameter_info(param_id)
        
        print(f"Parameter {param_id}:")
        print(f"  Name: {name}")
        print(f"  Bounds: {bounds}")
        print(f"  Mid value: {info.get('mid_value')}")
        print(f"  Normalized: {info.get('normalized_value')}")
        print()
    
    # Example 2: Parameter validation
    print("=== Parameter Validation ===")
    test_param = param_ids[0]
    min_val, max_val = manager.get_parameter_bounds(test_param)
    
    # Test various values
    test_values = [min_val, (min_val + max_val) / 2, max_val, min_val - 0.1, max_val + 0.1]
    
    for value in test_values:
        is_valid = manager.validate_parameter_value(test_param, value)
        status = "✓" if is_valid else "✗"
        print(f"  {status} Parameter {test_param} = {value:.3f}")
    
    # Example 3: Default parameters
    print("\n=== Default Parameters ===")
    defaults = manager.get_default_parameters()
    print(f"Generated {len(defaults)} default parameter values")
    
    # Show first few defaults
    for i, (param_id, default_val) in enumerate(list(defaults.items())[:5]):
        name = manager.get_parameter_name(param_id)
        print(f"  {param_id} ({name}): {default_val:.3f}")
    
    # Example 4: Constraint set validation
    print("\n=== Constraint Set Validation ===")
    
    # Valid constraint set
    valid_constraints: ParameterConstraintSet = {
        param_ids[0]: (0.2, 0.8),
        param_ids[1]: (0.0, 1.0),
        param_ids[2]: (0.3, 0.7)
    }
    
    is_valid = manager.validate_constraint_set(valid_constraints)
    print(f"Valid constraint set: {is_valid} ✓")
    
    # Invalid constraint set (out of bounds)
    invalid_constraints: ParameterConstraintSet = {
        param_ids[0]: (-0.1, 1.1),  # Outside parameter bounds
        param_ids[1]: (0.0, 1.0),
    }
    
    is_valid = manager.validate_constraint_set(invalid_constraints)
    print(f"Invalid constraint set: {is_valid} ✗")
    
    # Example 5: Parameter lookup by name
    print("\n=== Parameter Lookup ===")
    search_names = ["MasterVol", "A Vol", "A Pan"]
    
    for name in search_names:
        param_id = manager.find_parameter_by_name(name)
        if param_id:
            bounds = manager.get_parameter_bounds(param_id)
            print(f"  '{name}' -> Parameter {param_id}, bounds {bounds}")
        else:
            print(f"  '{name}' -> Not found")
    
    # Example 6: Working with parameter sets
    print("\n=== Parameter Set Operations ===")
    
    # Get a subset of parameters for oscillator A
    a_params = {}
    for param_id in param_ids:
        name = manager.get_parameter_name(param_id)
        if name and "A " in name:
            a_params[param_id] = manager.get_parameter_info(param_id)
    
    print(f"Found {len(a_params)} oscillator A parameters:")
    for param_id, info in list(a_params.items())[:3]:  # Show first 3
        print(f"  {param_id}: {info['name']} [{info['min_value']}, {info['max_value']}]")
    
    print("\n✓ Parameter manager demonstration complete!")


if __name__ == "__main__":
    main()