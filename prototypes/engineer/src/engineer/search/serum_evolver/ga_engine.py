from abc import ABC, abstractmethod
from typing import Dict, Any, List, Tuple, Optional
from pathlib import Path
import numpy as np
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from dataclasses import asdict
import os

# PyMoo imports
from pymoo.core.problem import Problem
from pymoo.algorithms.soo.nonconvex.ga import GA
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM
from pymoo.operators.sampling.rnd import FloatRandomSampling
from pymoo.operators.selection.rnd import RandomSelection
from pymoo.optimize import minimize
from pymoo.termination import get_termination
from pymoo.core.callback import Callback

from .interfaces import ParameterConstraintSet, ScalarFeatures, FeatureWeights, SerumParameters
from .parameter_manager import ISerumParameterManager
from .audio_generator import IAudioGenerator
from .feature_extractor import IFeatureExtractor
from .session_manager import ExperimentSessionManager

logger = logging.getLogger(__name__)


class GenerationLogger(Callback):
    """Callback to log generation statistics to a file for tailing."""
    
    def __init__(self, session_dir: Path):
        super().__init__()
        self.log_file = session_dir / "fitness_log.txt"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Write header
        with open(self.log_file, 'w') as f:
            f.write("generation,best_fitness,worst_fitness\n")
    
    def notify(self, algorithm):
        """Called after each generation."""
        try:
            gen = algorithm.n_gen
            pop = algorithm.pop
            
            # Extract fitness values from population
            fitness_values = []
            for ind in pop:
                if hasattr(ind.F, '__len__') and len(ind.F.shape) > 0:
                    fitness_values.append(float(ind.F.flatten()[0]))
                else:
                    fitness_values.append(float(ind.F))
            
            best_fitness = min(fitness_values)
            worst_fitness = max(fitness_values)
            
            # Log to file
            with open(self.log_file, 'a') as f:
                f.write(f"{gen},{best_fitness},{worst_fitness}\n")
                f.flush()
            
            logger.info(f"Generation {gen}: best={best_fitness:.4f}, worst={worst_fitness:.4f}")
            
        except Exception as e:
            logger.error(f"Error logging generation statistics: {e}")


class ArtifactManagerCallback(Callback):
    """Callback to log fitness data to ArtifactManager for organized experiment results."""
    
    def __init__(self, artifact_manager):
        super().__init__()
        self.artifact_manager = artifact_manager
    
    def notify(self, algorithm):
        """Called after each generation to log fitness data."""
        try:
            gen = algorithm.n_gen
            pop = algorithm.pop
            
            if pop is None or len(pop) == 0:
                logger.warning(f"Generation {gen}: No population data available")
                return
            
            # Collect individual fitness data
            individual_fitness = []
            for i, individual in enumerate(pop):
                if individual.F is not None and len(individual.F) > 0:
                    fitness = float(individual.F[0])
                    
                    # Extract parameters from genome (X)
                    params = {}
                    if individual.X is not None:
                        # Convert genome back to parameter dict using problem's constraint_set
                        problem = algorithm.problem
                        if hasattr(problem, 'constraint_set'):
                            param_keys = list(problem.constraint_set.keys())
                            for j, param_id in enumerate(param_keys):
                                if j < len(individual.X):
                                    params[param_id] = float(individual.X[j])
                    
                    individual_fitness.append((i, fitness, params))
            
            # Log fitness data to ArtifactManager
            if individual_fitness:
                self.artifact_manager.log_generation_fitness(gen, individual_fitness)
                logger.info(f"Logged fitness data for generation {gen}: {len(individual_fitness)} individuals")
            
        except Exception as e:
            logger.error(f"ArtifactManagerCallback error in generation {gen}: {e}")


class ISerumEvolver(ABC):
    """Interface for Serum evolutionary optimization."""

    @abstractmethod
    def evolve(self, constraint_set: ParameterConstraintSet,
              target_features: ScalarFeatures,
              feature_weights: FeatureWeights,
              n_generations: int = 10,
              population_size: int = 8) -> Dict[str, Any]:
        """Run evolutionary optimization."""
        pass


class SessionBasedSerumProblem(Problem):
    """
    Session-based GA problem for Serum parameter optimization.
    
    Evaluates entire populations as batch sessions rather than individual evaluations.
    Provides proper directory structure and target audio support.
    """
    
    def __init__(self, 
                 constraint_set: ParameterConstraintSet,
                 target_features: ScalarFeatures,
                 feature_weights: FeatureWeights,
                 session_manager: ExperimentSessionManager,
                 feature_extractor: IFeatureExtractor,
                 param_manager: ISerumParameterManager,
                 target_audio_path: Optional[Path] = None):
        """
        Initialize adaptive Serum optimization problem.
        
        Args:
            constraint_set: Parameter constraints defining search space
            target_features: Target feature values to optimize toward
            feature_weights: Weights for multi-objective feature optimization
            audio_generator: Audio generation interface
            feature_extractor: Feature extraction interface  
            param_manager: Parameter management interface
        """
        # Create adaptive genome mapping - only constrained parameters
        self.param_ids = list(constraint_set.keys())
        self.constraint_set = constraint_set
        self.target_features = target_features
        self.feature_weights = feature_weights
        self.session_manager = session_manager
        self.feature_extractor = feature_extractor
        self.param_manager = param_manager
        
        # Track generation for session creation
        self._current_generation = 1
        
        # Get genome size from constraint set
        n_var = len(self.param_ids)
        
        # Extract bounds from constraint set
        xl = np.array([constraint_set[param_id][0] for param_id in self.param_ids])
        xu = np.array([constraint_set[param_id][1] for param_id in self.param_ids])
        
        # Single objective (minimize feature distance)
        super().__init__(n_var=n_var, n_obj=1, xl=xl, xu=xu)
        
        # Cache default parameters for genome-to-parameter mapping
        self._default_params = self.param_manager.get_default_parameters()
        
        logger.info(f"Initialized adaptive GA problem with {n_var} parameters")
    
    def genome_to_parameters(self, genome: np.ndarray) -> SerumParameters:
        """
        Convert genome array to full Serum parameter dictionary.
        
        Args:
            genome: Array of parameter values for constrained parameters only
            
        Returns:
            Full Serum parameter dictionary with defaults for unconstrained parameters
        """
        if len(genome) != len(self.param_ids):
            raise ValueError(f"Genome size {len(genome)} doesn't match expected {len(self.param_ids)}")
        
        # Start with default parameters
        params = self._default_params.copy()
        
        # Override with genome values for constrained parameters
        for i, param_id in enumerate(self.param_ids):
            params[param_id] = float(genome[i])
        
        return params
    
    def parameters_to_genome(self, params: SerumParameters) -> np.ndarray:
        """
        Convert full parameter dictionary to genome array.
        
        Args:
            params: Full Serum parameter dictionary
            
        Returns:
            Genome array containing only constrained parameter values
        """
        genome = np.zeros(len(self.param_ids))
        
        for i, param_id in enumerate(self.param_ids):
            if param_id not in params:
                # Use constraint midpoint as fallback
                min_val, max_val = self.constraint_set[param_id]
                genome[i] = (min_val + max_val) / 2.0
                logger.warning(f"Parameter {param_id} not found, using midpoint {genome[i]}")
            else:
                genome[i] = params[param_id]
        
        return genome
    
    def _evaluate(self, x, out):
        """
        Evaluate population fitness using session-based batch rendering.
        
        Args:
            x: Population matrix (n_individuals × n_variables)  
            out: Output dictionary for objective values
        """
        n_individuals = x.shape[0]
        objectives = np.zeros(n_individuals)
        
        logger.info(f"Evaluating generation with {n_individuals} individuals using batch session")
        
        # Convert genomes to parameter sets
        population_params = []
        for i in range(n_individuals):
            params = self.genome_to_parameters(x[i])
            population_params.append(params)
        
        try:
            # Create session for this generation
            generation = getattr(self, '_current_generation', 1)
            session_dir = self.session_manager.create_generation_session(
                generation=generation,
                population_params=population_params
            )
            
            # Execute batch session
            success, audio_paths = self.session_manager.execute_session(session_dir)
            
            if success and len(audio_paths) == n_individuals:
                # Evaluate each individual's audio
                for i, audio_path in enumerate(audio_paths):
                    objectives[i] = self._evaluate_audio(audio_path, i)
                    
                # Update generation counter for next evaluation
                self._current_generation = generation + 1
            else:
                logger.error(f"Session execution failed or incomplete: {len(audio_paths)}/{n_individuals} audio files")
                objectives.fill(float('inf'))
                
        except Exception as e:
            logger.error(f"Batch evaluation failed: {e}")
            objectives.fill(float('inf'))
        
        out["F"] = objectives.reshape(-1, 1)  # pymoo expects column vector
    
    def _evaluate_audio(self, audio_path: Path, individual_id: int) -> float:
        """
        Evaluate fitness for a rendered audio file.
        
        Args:
            audio_path: Path to rendered audio file
            individual_id: Unique identifier for this individual
            
        Returns:
            Fitness value (distance to target features)
        """
        try:
            if audio_path and audio_path.exists():
                # Extract features from generated audio
                actual_features = self.feature_extractor.extract_scalar_features(
                    audio_path, self.feature_weights
                )
                
                # Compute fitness as feature distance (minimize)
                distance = self.feature_extractor.compute_feature_distance(
                    self.target_features, actual_features, self.feature_weights
                )
                
                logger.debug(f"Individual {individual_id}: distance = {distance:.4f}")
                return distance
                
            else:
                # Penalize missing audio files
                logger.warning(f"Audio file not found: {audio_path}")
                return float('inf')
                
        except Exception as e:
            # Penalize individuals that cause errors
            logger.error(f"Error evaluating audio for individual {individual_id}: {str(e)}")
            return float('inf')


class AdaptiveSerumEvolver(ISerumEvolver):
    """
    Adaptive genetic algorithm implementation for Serum parameter optimization.
    
    Features:
    - Adaptive genome sizing based on constraint set
    - Parallel population evaluation 
    - Integration with all serum_evolver components
    - JSI-compatible result formatting
    - Comprehensive error handling and logging
    """
    
    def __init__(self,
                 session_manager: ExperimentSessionManager,
                 feature_extractor: IFeatureExtractor, 
                 param_manager: ISerumParameterManager):
        """
        Initialize session-based Serum evolver.
        
        Args:
            session_manager: Experiment session manager
            feature_extractor: Feature extraction interface
            param_manager: Parameter management interface
        """
        self.session_manager = session_manager
        self.feature_extractor = feature_extractor
        self.param_manager = param_manager
        
        logger.info(f"Initialized SessionBasedSerumEvolver for experiment: {session_manager.experiment_name}")
    
    def evolve(self, 
               constraint_set: ParameterConstraintSet,
               target_features: ScalarFeatures,
               feature_weights: FeatureWeights,
               n_generations: int = 10,
               population_size: int = 8,
               session_dir: Optional[Path] = None) -> Dict[str, Any]:
        """
        Run evolutionary optimization to find Serum parameters matching target features.
        
        Args:
            constraint_set: Parameters to evolve with their bounds
            target_features: Target audio features to match
            feature_weights: Importance weights for different features
            n_generations: Number of generations to evolve
            population_size: Size of population per generation
            session_dir: Directory for session files and logging
            
        Returns:
            Dictionary containing evolution results with JSI-compatible format:
            - best_individual: Best parameter set found
            - best_fitness: Fitness of best individual
            - fitness_history: Fitness progression over generations
            - population_diversity: Diversity metrics per generation
            - generation_stats: Statistics for each generation
            - jsi_ranking_candidates: Top candidates formatted for JSI ranking
            
        Raises:
            ValueError: If inputs are invalid
            RuntimeError: If evolution fails
        """
        start_time = time.time()
        
        # Validate inputs
        if not constraint_set:
            raise ValueError("Constraint set cannot be empty")
        
        if not self.param_manager.validate_constraint_set(constraint_set):
            raise ValueError("Invalid constraint set")
        
        active_features = feature_weights.get_active_features()
        if not active_features:
            raise ValueError("At least one feature weight must be non-zero")
        
        logger.info(f"Starting evolution: {len(constraint_set)} parameters, "
                   f"{len(active_features)} active features, "
                   f"{n_generations} generations, {population_size} population")
        
        try:
            # Create session-based problem
            problem = SessionBasedSerumProblem(
                constraint_set=constraint_set,
                target_features=target_features,
                feature_weights=feature_weights,
                session_manager=self.session_manager,
                feature_extractor=self.feature_extractor,
                param_manager=self.param_manager
            )
            
            # Configure GA algorithm
            algorithm = GA(
                pop_size=population_size,
                sampling=FloatRandomSampling(),
                crossover=SBX(prob=0.9, eta=15),
                mutation=PM(prob=1.0/len(constraint_set), eta=20),
                selection=RandomSelection()  # Use random selection for simplicity
            )
            
            # Set termination criteria
            termination = get_termination("n_gen", n_generations)
            
            # Create generation logger callback if session_dir provided
            callback = None
            if session_dir:
                callback = GenerationLogger(session_dir)
                logger.info(f"Generation logging enabled: {callback.log_file}")
            
            # Setup ArtifactManager callback if available
            artifact_callback = None
            if hasattr(self.session_manager, 'artifact_manager') and self.session_manager.artifact_manager:
                artifact_callback = ArtifactManagerCallback(self.session_manager.artifact_manager)
                logger.info("ArtifactManager fitness logging enabled")
            
            # Use single callback - prefer artifact_callback if both exist
            callback_param = artifact_callback if artifact_callback else callback
            
            # Run optimization
            logger.info("Starting pymoo optimization")
            result = minimize(
                problem,
                algorithm, 
                termination,
                callback=callback_param,
                verbose=True,
                seed=42
            )
            
            # Process results
            evolution_results = self._process_results(
                result, problem, constraint_set, target_features, 
                feature_weights, start_time
            )
            
            logger.info(f"Evolution completed in {time.time() - start_time:.2f}s. "
                       f"Best fitness: {evolution_results['best_fitness']:.4f}")
            
            return evolution_results
            
        except Exception as e:
            logger.error(f"Evolution failed: {str(e)}")
            raise RuntimeError(f"Evolutionary optimization failed: {str(e)}")
    
    def _process_results(self, 
                        result, 
                        problem: SessionBasedSerumProblem,
                        constraint_set: ParameterConstraintSet,
                        target_features: ScalarFeatures,
                        feature_weights: FeatureWeights,
                        start_time: float) -> Dict[str, Any]:
        """Process pymoo results into comprehensive evolution summary."""
        
        # Check if we have valid results
        if result.X is None or result.F is None:
            logger.warning("No valid solution found during evolution")
            # Return empty results
            return {
                'best_individual': {},
                'best_parameters': {},
                'best_fitness': float('inf'),
                'fitness_history': [],
                'population_diversity': [0.0],
                'generation_stats': [],
                'jsi_ranking_candidates': [],
                'evolution_metadata': {
                    'total_time': time.time() - start_time,
                    'constraint_set_size': len(constraint_set),
                    'active_features': len(feature_weights.get_active_features()),
                    'generations_run': 0
                },
                'performance_metrics': {
                    'avg_evaluation_time': 0.0,
                    'total_evaluations': 0,
                    'convergence_generation': -1
                }
            }
        
        # Extract best individual
        best_genome = result.X
        # Handle both scalar and array F values
        if hasattr(result.F, '__len__') and len(result.F.shape) > 0:
            best_fitness = float(result.F.flatten()[0])
        else:
            best_fitness = float(result.F)
        best_params = problem.genome_to_parameters(best_genome)
        
        # Get final population for diversity analysis
        final_population = result.pop
        population_genomes = np.array([ind.X for ind in final_population])
        population_fitness = np.array([float(ind.F.flatten()[0]) if hasattr(ind.F, '__len__') else float(ind.F) 
                                     for ind in final_population])
        
        # Calculate population diversity (average pairwise distance)
        diversity_scores = []
        if len(population_genomes) > 1:
            for i in range(len(population_genomes)):
                for j in range(i + 1, len(population_genomes)):
                    dist = np.linalg.norm(population_genomes[i] - population_genomes[j])
                    diversity_scores.append(dist)
        
        avg_diversity = np.mean(diversity_scores) if diversity_scores else 0.0
        
        # Extract fitness history from algorithm history
        fitness_history = []
        generation_stats = []
        
        if hasattr(result.algorithm, 'callback') and hasattr(result.algorithm.callback, 'data'):
            try:
                for gen_data in result.algorithm.callback.data['best']:
                    if hasattr(gen_data.F, '__len__'):
                        fitness_history.append(float(gen_data.F.flatten()[0]))
                    else:
                        fitness_history.append(float(gen_data.F))
            except (KeyError, AttributeError):
                # Fallback if callback structure is different
                fitness_history = [best_fitness]
        else:
            # Fallback - create basic history
            fitness_history = [best_fitness]
            
        # Generate statistics for each generation
        for gen in range(len(fitness_history)):
            gen_stats = {
                'generation': gen,
                'best_fitness': fitness_history[gen] if gen < len(fitness_history) else best_fitness,
                'avg_fitness': fitness_history[gen] if gen < len(fitness_history) else best_fitness,  # Simplified
                'diversity': avg_diversity  # Simplified - would need per-generation tracking
            }
            generation_stats.append(gen_stats)
        
        # Prepare JSI ranking candidates (top N individuals)
        n_candidates = min(5, len(final_population))
        jsi_candidates = []
        
        # Sort population by fitness
        sorted_indices = np.argsort(population_fitness)
        
        for i in range(n_candidates):
            idx = sorted_indices[i]
            candidate_genome = population_genomes[idx]
            candidate_params = problem.genome_to_parameters(candidate_genome)
            candidate_fitness = population_fitness[idx]
            
            jsi_candidate = {
                'rank': i + 1,
                'fitness': float(candidate_fitness),
                'parameters': candidate_params,
                'genome': candidate_genome.tolist(),
                'parameter_ids': problem.param_ids
            }
            jsi_candidates.append(jsi_candidate)
        
        # Compile comprehensive results
        evolution_results = {
            # Core results
            'best_individual': best_params,
            'best_parameters': best_params,  # Alias for compatibility
            'best_fitness': best_fitness,
            'best_genome': best_genome.tolist(),
            
            # Evolution tracking
            'fitness_history': fitness_history,
            'generation_stats': generation_stats,
            'population_diversity': avg_diversity,
            'generations_run': len(fitness_history),
            
            # JSI integration
            'jsi_ranking_candidates': jsi_candidates,
            
            # Metadata
            'evolution_metadata': {
                'constraint_set': constraint_set,
                'target_features': asdict(target_features),
                'feature_weights': asdict(feature_weights),
                'n_generations': len(fitness_history),
                'population_size': len(final_population),
                'n_parameters': len(constraint_set),
                'active_features': list(feature_weights.get_active_features().keys()),
                'evolution_time': time.time() - start_time,
                'convergence_achieved': best_fitness < 1.0,  # Arbitrary threshold
            },
            
            # Performance metrics
            'performance_metrics': {
                'total_evaluations': len(fitness_history) * len(final_population),
                'avg_evaluation_time': (time.time() - start_time) / (len(fitness_history) * len(final_population)),
                'convergence_generation': self._find_convergence_generation(fitness_history),
                'improvement_ratio': (fitness_history[0] - best_fitness) / fitness_history[0] if fitness_history else 0.0
            }
        }
        
        return evolution_results
    
    def _find_convergence_generation(self, fitness_history: List[float], 
                                   threshold: float = 0.01) -> Optional[int]:
        """
        Find the generation where fitness converged (stopped improving significantly).
        
        Args:
            fitness_history: List of best fitness values per generation
            threshold: Improvement threshold to consider converged
            
        Returns:
            Generation number where convergence occurred, or None
        """
        if len(fitness_history) < 3:
            return None
        
        for i in range(2, len(fitness_history)):
            # Check if improvement over last 2 generations is below threshold
            recent_improvement = abs(fitness_history[i-2] - fitness_history[i])
            if recent_improvement < threshold:
                return i
        
        return None


