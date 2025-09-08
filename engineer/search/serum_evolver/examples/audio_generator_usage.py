"""
Example usage of SerumAudioGenerator for GA population initialization and audio rendering.
"""

from pathlib import Path
import logging
import sys

# Add the project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from serum_evolver.audio_generator import SerumAudioGenerator
from serum_evolver.parameter_manager import SerumParameterManager
from serum_evolver.interfaces import ParameterConstraintSet


def main():
    """Demonstrate SerumAudioGenerator usage."""
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Paths
    reaper_path = project_root / "reaper"
    fx_params_path = reaper_path / "fx_parameters.json"
    
    print("SerumAudioGenerator Usage Example")
    print("=" * 40)
    
    # Check if required files exist
    if not reaper_path.exists():
        print(f"❌ REAPER directory not found: {reaper_path}")
        print("Please ensure the REAPER project directory exists.")
        return
    
    if not fx_params_path.exists():
        print(f"❌ FX parameters file not found: {fx_params_path}")
        print("Please ensure fx_parameters.json exists in the REAPER directory.")
        return
    
    try:
        # Initialize components
        print("🔧 Initializing parameter manager...")
        param_manager = SerumParameterManager(fx_params_path)
        
        print("🔧 Initializing audio generator...")
        audio_generator = SerumAudioGenerator(reaper_path, param_manager)
        
        print(f"✅ Loaded {len(param_manager.get_all_parameter_ids())} Serum parameters")
        
        # Example 1: Generate random patch with constraints
        print("\n📊 Example 1: Random patch generation with constraints")
        print("-" * 50)
        
        # Define constraints for GA optimization
        constraint_set: ParameterConstraintSet = {
            "4": (0.2, 0.8),  # A Octave: constrain to middle range
            "5": (0.0, 0.6),  # A Fine: constrain to lower range
        }
        
        print(f"Constraint set: {constraint_set}")
        
        # Generate random parameters (this would be used by GA for population initialization)
        random_params = audio_generator._generate_random_parameters(constraint_set)
        print(f"Generated random parameters: {random_params}")
        
        # Get default parameters
        defaults = param_manager.get_default_parameters()
        print(f"Default parameters (showing first 5): {dict(list(defaults.items())[:5])}")
        
        # Example 2: Create session configuration (without actual REAPER execution)
        print("\n🎵 Example 2: Session configuration creation")
        print("-" * 50)
        
        session_name = "example_session"
        test_params = {
            "1": 0.75,  # MasterVol
            "4": 0.6,   # A Octave  
            "5": 0.25   # A Fine
        }
        
        print(f"Creating session config for: {test_params}")
        config_path = audio_generator.reaper_session_manager.create_session_config(
            session_name, test_params
        )
        print(f"✅ Session config created: {config_path}")
        
        # Verify config structure
        import json
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        render_config = config["render_configs"][0]
        print(f"   - Render ID: {render_config['render_id']}")
        print(f"   - Parameters count: {len(render_config['parameters'])}")
        print(f"   - BPM: {render_config['render_options']['bpm']}")
        print(f"   - Note: {render_config['render_options']['note']}")
        print(f"   - Duration: {render_config['render_options']['duration']}")
        
        # Example 3: Parameter validation
        print("\n✅ Example 3: Parameter validation")
        print("-" * 50)
        
        # Test valid parameters
        valid_param_id = "4"
        valid_value = 0.5
        is_valid = param_manager.validate_parameter_value(valid_param_id, valid_value)
        print(f"Parameter {valid_param_id}={valid_value} is valid: {is_valid}")
        
        # Test invalid parameters
        invalid_value = 2.0
        is_valid = param_manager.validate_parameter_value(valid_param_id, invalid_value)
        print(f"Parameter {valid_param_id}={invalid_value} is valid: {is_valid}")
        
        # Test constraint validation
        valid_constraints = {"4": (0.2, 0.8)}
        is_valid = param_manager.validate_constraint_set(valid_constraints)
        print(f"Constraints {valid_constraints} are valid: {is_valid}")
        
        invalid_constraints = {"4": (0.5, 2.0)}  # max exceeds parameter bounds
        is_valid = param_manager.validate_constraint_set(invalid_constraints)
        print(f"Constraints {invalid_constraints} are valid: {is_valid}")
        
        # Example 4: GA Population Initialization Simulation
        print("\n🧬 Example 4: GA population initialization simulation")
        print("-" * 50)
        
        population_size = 4
        print(f"Simulating GA population initialization with {population_size} individuals...")
        
        population = []
        for i in range(population_size):
            # Generate random parameters within constraints
            individual_params = audio_generator._generate_random_parameters(constraint_set)
            
            # Get full parameter set (defaults + generated)
            full_params = param_manager.get_default_parameters()
            full_params.update(individual_params)
            
            population.append({
                'id': f"individual_{i+1}",
                'constrained_params': individual_params,
                'full_params': full_params
            })
            
            print(f"   Individual {i+1}: {individual_params}")
        
        print(f"✅ Generated {len(population)} individuals for GA population")
        
        # Example 5: Concurrent session handling
        print("\n🔄 Example 5: Concurrent session name generation")
        print("-" * 50)
        
        import uuid
        session_names = []
        for i in range(5):
            session_name = f"random_{uuid.uuid4().hex[:8]}"
            session_names.append(session_name)
        
        print("Generated unique session names for concurrent GA operations:")
        for name in session_names:
            print(f"   - {name}")
        
        print(f"✅ All {len(session_names)} session names are unique: {len(set(session_names)) == len(session_names)}")
        
        # Cleanup
        print("\n🧹 Cleanup")
        print("-" * 50)
        config_path.unlink()
        print("✅ Cleaned up example session config")
        
        print("\n🎉 SerumAudioGenerator demo completed successfully!")
        print("\nKey Features Demonstrated:")
        print("✅ Random parameter generation within constraints")
        print("✅ REAPER session configuration creation")
        print("✅ Parameter validation and bounds checking") 
        print("✅ Integration with existing parameter manager")
        print("✅ GA population initialization simulation")
        print("✅ Concurrent session management")
        print("\nNext Steps:")
        print("- Integrate with GA engine for actual optimization")
        print("- Run with real REAPER for audio generation")
        print("- Connect to fitness evaluation system")
        
    except Exception as e:
        print(f"❌ Error during demonstration: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()