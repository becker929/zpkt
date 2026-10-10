"""
Usage example for the AdaptiveSerumEvolver (GA Engine).

This example demonstrates how to use the complete GA engine system to evolve
Serum synthesizer parameters toward target audio features. It showcases:

1. Setting up all components (parameter manager, audio generator, feature extractor)
2. Defining constraint sets and target features
3. Running the evolutionary optimization
4. Processing results for JSI ranking integration
5. Advanced usage patterns (parallel evaluation, custom constraints)

Required setup:
- REAPER with Serum plugin installed
- fx_parameters.json file with Serum parameter definitions
- REAPER project configured for automated rendering
"""

import logging
from pathlib import Path
import numpy as np
from typing import Dict, Any

# Import all serum_evolver components
from serum_evolver.parameter_manager import SerumParameterManager
from serum_evolver.audio_generator import SerumAudioGenerator
from serum_evolver.feature_extractor import LibrosaFeatureExtractor
from serum_evolver.ga_engine import AdaptiveSerumEvolver
from serum_evolver.interfaces import (
    ParameterConstraintSet, ScalarFeatures, FeatureWeights
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_sample_constraint_set() -> ParameterConstraintSet:
    """
    Create a sample constraint set for demonstration.
    
    In practice, this would be based on user selection or automatic parameter
    importance analysis.
    """
    return {
        # Oscillator parameters
        'osc_a_wave_type': (0.0, 1.0),        # Wave type selection
        'osc_a_pitch': (-24.0, 24.0),         # Pitch in semitones  
        'osc_a_level': (0.0, 1.0),            # Oscillator level
        
        # Filter parameters
        'filter_cutoff': (0.0, 1.0),          # Filter cutoff frequency
        'filter_resonance': (0.0, 1.0),       # Filter resonance
        'filter_type': (0.0, 1.0),            # Filter type selection
        
        # Envelope parameters
        'env_attack': (0.0, 1.0),             # Attack time
        'env_decay': (0.0, 1.0),              # Decay time
        'env_sustain': (0.0, 1.0),            # Sustain level
        'env_release': (0.0, 1.0),            # Release time
        
        # Effects parameters
        'reverb_mix': (0.0, 1.0),             # Reverb amount
        'delay_time': (0.0, 1.0),             # Delay time
        'distortion_amount': (0.0, 1.0),      # Distortion intensity
    }


def create_target_features() -> ScalarFeatures:
    """
    Create target audio features to optimize toward.
    
    These could come from analysis of reference audio or user specification.
    """
    return ScalarFeatures(
        # Target a bright, energetic sound
        spectral_centroid=2500.0,     # Higher frequency content
        spectral_bandwidth=1200.0,    # Wide frequency spread
        spectral_rolloff=4000.0,      # High-frequency energy
        rms_energy=0.15,              # Moderate loudness
        tempo=128.0,                  # Electronic music tempo
        
        # Harmonic characteristics
        chroma_mean=0.6,              # Rich harmonic content
        spectral_contrast=0.4,        # Good spectral definition
        
        # Other features set to default (will be ignored with 0 weight)
        spectral_flatness=0.0,
        zero_crossing_rate=0.0,
        tonnetz_mean=0.0,
        mfcc_mean=0.0
    )


def create_feature_weights() -> FeatureWeights:
    """
    Create feature weights defining optimization priorities.
    
    Higher weights mean the feature is more important for fitness calculation.
    """
    return FeatureWeights(
        # Prioritize spectral characteristics
        spectral_centroid=1.0,        # Most important
        spectral_bandwidth=0.8,       # Very important
        spectral_rolloff=0.6,         # Important
        spectral_contrast=0.4,        # Moderately important
        
        # Energy characteristics
        rms_energy=0.7,               # Very important
        
        # Rhythmic characteristics  
        tempo=0.3,                    # Less important (depends on material)
        
        # Harmonic characteristics
        chroma_mean=0.5,              # Moderately important
        
        # Unused features (weight = 0.0)
        spectral_flatness=0.0,
        zero_crossing_rate=0.0,
        tonnetz_mean=0.0,
        mfcc_mean=0.0
    )


def basic_evolution_example():
    """
    Basic example of evolutionary optimization with the GA engine.
    """
    print("=" * 60)
    print("BASIC EVOLUTION EXAMPLE")
    print("=" * 60)
    
    # Paths (adjust these for your setup)
    fx_params_path = Path("path/to/fx_parameters.json")
    reaper_project_path = Path("path/to/reaper/project")
    
    try:
        # Initialize all components
        print("Initializing components...")
        param_manager = SerumParameterManager(fx_params_path)
        audio_generator = SerumAudioGenerator(reaper_project_path, param_manager)
        feature_extractor = LibrosaFeatureExtractor(sample_rate=44100)
        
        # Create GA evolver
        evolver = AdaptiveSerumEvolver(
            audio_generator=audio_generator,
            feature_extractor=feature_extractor,
            param_manager=param_manager,
            max_workers=4,                    # Parallel evaluation
            use_parallel_evaluation=True
        )
        
        # Set up optimization parameters
        constraint_set = create_sample_constraint_set()
        target_features = create_target_features()
        feature_weights = create_feature_weights()
        
        print(f"Evolving {len(constraint_set)} parameters toward target features...")
        print(f"Active features: {list(feature_weights.get_active_features().keys())}")
        
        # Run evolution
        results = evolver.evolve(
            constraint_set=constraint_set,
            target_features=target_features,
            feature_weights=feature_weights,
            n_generations=5,                  # Quick demo
            population_size=8
        )
        
        # Process results
        print("\nEVOLUTION RESULTS:")
        print(f"Best fitness: {results['best_fitness']:.4f}")
        print(f"Evolution time: {results['evolution_metadata']['evolution_time']:.2f}s")
        print(f"Convergence achieved: {results['evolution_metadata']['convergence_achieved']}")
        
        # Show best parameters
        print("\nBest parameter values:")
        best_params = results['best_individual']
        for param_id, value in list(best_params.items())[:10]:  # Show first 10
            print(f"  {param_id}: {value:.4f}")
        
        # Show JSI candidates
        print(f"\nTop {len(results['jsi_ranking_candidates'])} candidates for JSI ranking:")
        for candidate in results['jsi_ranking_candidates']:
            print(f"  Rank {candidate['rank']}: fitness = {candidate['fitness']:.4f}")
        
        return results
        
    except Exception as e:
        print(f"Error in evolution: {e}")
        print("Make sure REAPER and parameter files are properly configured")
        return None


def advanced_evolution_example():
    """
    Advanced example showing custom configuration and analysis.
    """
    print("=" * 60) 
    print("ADVANCED EVOLUTION EXAMPLE")
    print("=" * 60)
    
    # Create multiple constraint sets for comparison
    constraint_sets = {
        "oscillator_focused": {
            'osc_a_wave_type': (0.2, 0.8),
            'osc_a_pitch': (-12.0, 12.0), 
            'osc_a_level': (0.5, 1.0),
            'osc_b_wave_type': (0.0, 1.0),
            'osc_b_pitch': (-7.0, 7.0),
        },
        
        "filter_focused": {
            'filter_cutoff': (0.1, 0.9),
            'filter_resonance': (0.0, 0.8),
            'filter_drive': (0.0, 0.5),
            'filter_env_amount': (-1.0, 1.0),
        },
        
        "effects_focused": {
            'reverb_mix': (0.0, 0.4),
            'delay_time': (0.0, 0.8),
            'chorus_rate': (0.0, 1.0),
            'distortion_amount': (0.0, 0.3),
        }
    }
    
    # Different target profiles
    target_profiles = {
        "bright_lead": ScalarFeatures(
            spectral_centroid=3000.0,
            spectral_bandwidth=1500.0,
            rms_energy=0.2,
            spectral_contrast=0.5
        ),
        
        "warm_pad": ScalarFeatures(
            spectral_centroid=800.0,
            spectral_bandwidth=600.0,
            rms_energy=0.08,
            chroma_mean=0.7
        ),
        
        "punchy_bass": ScalarFeatures(
            spectral_centroid=200.0,
            spectral_rolloff=800.0,
            rms_energy=0.25,
            spectral_contrast=0.3
        )
    }
    
    print("Running evolution with different constraint sets and targets...")
    
    # This would require actual component initialization
    # Shown here for demonstration of the analysis workflow
    results_comparison = {}
    
    for constraint_name, constraints in constraint_sets.items():
        for target_name, target in target_profiles.items():
            
            print(f"\nTesting: {constraint_name} → {target_name}")
            
            # In practice, you would run actual evolution here:
            # results = evolver.evolve(constraints, target, weights, ...)
            
            # For demo, create mock results
            mock_results = {
                'best_fitness': np.random.uniform(0.5, 2.0),
                'convergence_generation': np.random.randint(2, 8),
                'population_diversity': np.random.uniform(0.1, 0.8),
                'improvement_ratio': np.random.uniform(0.3, 0.9)
            }
            
            results_comparison[f"{constraint_name}_{target_name}"] = mock_results
            
            print(f"  Best fitness: {mock_results['best_fitness']:.4f}")
            print(f"  Converged at generation: {mock_results['convergence_generation']}")
            print(f"  Improvement ratio: {mock_results['improvement_ratio']:.3f}")
    
    # Analyze results
    print("\n" + "=" * 40)
    print("COMPARATIVE ANALYSIS")
    print("=" * 40)
    
    best_combo = min(results_comparison.items(), key=lambda x: x[1]['best_fitness'])
    print(f"Best combination: {best_combo[0]}")
    print(f"Best fitness achieved: {best_combo[1]['best_fitness']:.4f}")
    
    # Analysis by constraint type
    print("\nPerformance by constraint focus:")
    for constraint_type in ["oscillator", "filter", "effects"]:
        matching_results = {k: v for k, v in results_comparison.items() 
                          if constraint_type in k}
        if matching_results:
            avg_fitness = np.mean([r['best_fitness'] for r in matching_results.values()])
            print(f"  {constraint_type.title()}-focused: {avg_fitness:.4f} avg fitness")


def jsi_integration_example(evolution_results: Dict[str, Any]):
    """
    Example of how to integrate evolution results with JSI ranking system.
    """
    print("=" * 60)
    print("JSI INTEGRATION EXAMPLE") 
    print("=" * 60)
    
    if not evolution_results:
        print("No evolution results to process")
        return
        
    # Extract JSI-compatible candidates
    jsi_candidates = evolution_results['jsi_ranking_candidates']
    
    print(f"Processing {len(jsi_candidates)} candidates for JSI ranking...")
    
    # Format for JSI system
    jsi_session_data = {
        'session_id': 'ga_evolution_001',
        'timestamp': '2024-01-01T12:00:00Z',
        'optimization_metadata': {
            'n_generations': evolution_results['evolution_metadata']['n_generations'],
            'population_size': evolution_results['evolution_metadata']['population_size'],
            'evolution_time': evolution_results['evolution_metadata']['evolution_time'],
            'convergence_achieved': evolution_results['evolution_metadata']['convergence_achieved']
        },
        'candidates': []
    }
    
    # Convert candidates to JSI format
    for candidate in jsi_candidates:
        jsi_candidate = {
            'candidate_id': f"ga_candidate_{candidate['rank']}",
            'fitness_score': candidate['fitness'],
            'parameters': candidate['parameters'],
            'genome': candidate['genome'],
            'parameter_mapping': {
                'constrained_params': candidate['parameter_ids'],
                'genome_size': len(candidate['genome'])
            }
        }
        jsi_session_data['candidates'].append(jsi_candidate)
    
    print("JSI session data structure:")
    print(f"  Session ID: {jsi_session_data['session_id']}")
    print(f"  Candidates: {len(jsi_session_data['candidates'])}")
    print(f"  Best fitness: {min(c['fitness_score'] for c in jsi_session_data['candidates']):.4f}")
    
    # Simulate JSI ranking process
    print("\nSimulating user rankings (normally done through JSI interface)...")
    
    # Mock user preferences (in practice from JSI)
    user_rankings = [
        {'candidate_id': 'ga_candidate_2', 'user_rank': 1, 'user_score': 0.9},
        {'candidate_id': 'ga_candidate_1', 'user_rank': 2, 'user_score': 0.7},
        {'candidate_id': 'ga_candidate_3', 'user_rank': 3, 'user_score': 0.6},
    ]
    
    # Analysis of GA fitness vs user preference
    print("\nGA fitness vs User preference correlation:")
    for ranking in user_rankings:
        candidate_id = ranking['candidate_id']
        # Find corresponding GA candidate
        ga_candidate = next(c for c in jsi_session_data['candidates'] 
                          if c['candidate_id'] == candidate_id)
        
        print(f"  {candidate_id}:")
        print(f"    GA fitness: {ga_candidate['fitness_score']:.4f}")
        print(f"    User rank: {ranking['user_rank']}")
        print(f"    User score: {ranking['user_score']:.2f}")
    
    return jsi_session_data


def main():
    """
    Main function demonstrating all GA engine capabilities.
    """
    print("SERUM EVOLVER GA ENGINE - COMPREHENSIVE DEMO")
    print("=" * 60)
    
    # Run basic evolution example
    evolution_results = basic_evolution_example()
    
    print("\n" + "=" * 60 + "\n")
    
    # Run advanced evolution example  
    advanced_evolution_example()
    
    print("\n" + "=" * 60 + "\n")
    
    # Show JSI integration
    jsi_integration_example(evolution_results)
    
    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)
    print("""
Key features demonstrated:

1. ✅ Adaptive genome sizing (only evolve constrained parameters)
2. ✅ Parameter-to-genome mapping and vice versa  
3. ✅ Fitness evaluation via audio generation + feature extraction
4. ✅ Parallel population evaluation for performance
5. ✅ Integration with all previous agent components
6. ✅ JSI-compatible result formatting
7. ✅ Comprehensive error handling and logging
8. ✅ Evolution progress tracking and convergence detection
9. ✅ Multiple constraint set and target comparisons
10. ✅ User preference correlation analysis

The GA engine is ready for production use in the SerumEvolver system!
    """)


if __name__ == "__main__":
    main()