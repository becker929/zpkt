"""Core GA+JSI+Audio Oracle engine for web-based optimization."""

import uuid
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import sys

# Add demo paths to import from existing implementations
sys.path.append(str(Path(__file__).parent.parent.parent / "demos" / "ga_jsi_audio_oracle"))
sys.path.append(str(Path(__file__).parent.parent.parent / "demos" / "choix_active_online"))

from pymoo.algorithms.soo.nonconvex.ga import GA
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM
from pymoo.operators.sampling.rnd import FloatRandomSampling
from pymoo.optimize import minimize
from pymoo.termination import get_termination

from ga_jsi_audio_oracle.ga_problem import JSIAudioOptimizationProblem
from ga_jsi_audio_oracle.audio_oracle import AudioComparisonOracle
from choix_active_online_demo.comparison_oracle import ComparisonOracle

from .database import Database


class WebGAJSIEngine:
    """Web-based GA+JSI+Audio Oracle optimization engine."""

    def __init__(self, database: Database, reaper_project_path: Path):
        """Initialize the optimization engine.

        Args:
            database: Database instance for persistence
            reaper_project_path: Path to REAPER project directory
        """
        self.db = database
        self.db._init_database()  # Ensure database tables exist
        self.reaper_project_path = reaper_project_path
        self.current_session_id: Optional[str] = None
        self.current_problem: Optional[JSIAudioOptimizationProblem] = None
        self.comparison_oracle: Optional[ComparisonOracle] = None

    def create_session(self, name: str, target_frequency: Optional[float] = None,
                      population_size: int = 8, config: Optional[Dict[str, Any]] = None) -> str:
        """Create new GA optimization session.

        Args:
            name: Human-readable session name
            target_frequency: Target frequency for optimization
            population_size: Size of GA population
            config: Additional configuration parameters

        Returns:
            Session ID
        """
        session_id = str(uuid.uuid4())

        # Store session in database
        self.db.create_ga_session(
            session_id=session_id,
            name=name,
            target_frequency=target_frequency,
            population_size=population_size,
            config=config or {}
        )

        self.current_session_id = session_id
        return session_id

    def initialize_population(self, session_id: str) -> Dict[str, Any]:
        """Initialize first population for GA session.

        Args:
            session_id: GA session ID

        Returns:
            Population information
        """
        session = self.db.get_ga_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Create GA problem instance
        self.current_problem = JSIAudioOptimizationProblem(
            reaper_project_path=self.reaper_project_path,
            target_frequency=session['target_frequency'] or 440.0,
            session_name_prefix=f"web_session_{session_id[:8]}",
            oracle_noise_level=0.0,  # Use real user feedback
            show_live_ranking=False  # Disable console output for web
        )

        # Initialize algorithm
        algorithm = GA(
            pop_size=session['population_size'],
            sampling=FloatRandomSampling(),
            crossover=SBX(prob=0.9, eta=15),
            mutation=PM(prob=0.1, eta=20),
            eliminate_duplicates=True
        )

        # Generate initial population using sampling directly
        problem = self.current_problem
        sampling = FloatRandomSampling()
        pop = sampling.do(problem, session['population_size'])

        # Create population record
        population_id = str(uuid.uuid4())
        self.db.add_population(population_id, session_id, 0)

        # Render audio for initial population and store solutions
        solutions_info = []
        for i, individual in enumerate(pop):
            solution_id = str(uuid.uuid4())

            # Convert pymoo individual to parameters
            parameters = {
                'octave': individual.X[0],
                'fine_tuning': individual.X[1] if len(individual.X) > 1 else 0.0
            }

            # For now, use existing rendered audio files for testing
            try:
                audio_file_id = self._find_existing_audio_file(solution_id, parameters)
                if not audio_file_id:
                    print(f"No existing audio file found for solution {solution_id}")

            except Exception as e:
                print(f"Failed to find audio for solution {solution_id}: {e}")
                audio_file_id = None

            # Store solution in database
            self.db.add_solution(
                solution_id=solution_id,
                population_id=population_id,
                parameters=parameters,
                audio_file_id=audio_file_id
            )

            solutions_info.append({
                'id': solution_id,
                'parameters': parameters,
                'audio_file_id': audio_file_id
            })

        # Generate initial comparison pairs
        comparison_pairs = self._generate_comparison_pairs(solutions_info)

        return {
            'population_id': population_id,
            'generation': 0,
            'solutions': solutions_info,
            'comparison_pairs_generated': len(comparison_pairs)
        }

    def _render_solution_audio(self, solution_id: str, parameters: Dict[str, Any]) -> Optional[Path]:
        """Render audio for a solution using REAPER.

        Args:
            solution_id: Unique solution identifier
            parameters: Solution parameters

        Returns:
            Path to rendered audio file or None if failed
        """
        if not self.current_problem:
            return None

        try:
            # Import the Solution class from the demo
            sys.path.append(str(Path(__file__).parent.parent.parent / "demos" / "pymoo_ga_freq_reaper"))
            from ga_frequency_demo.genetics import Solution

            # Create a proper Solution object
            solution = Solution(
                octave=parameters['octave'],
                fine=parameters.get('fine_tuning', 0.0)
            )

            # Use the population renderer with a single solution
            session_name = f"web_solution_{solution_id[:8]}"
            audio_paths = self.current_problem._render_population_audio([solution], session_name)

            # Return the first (and only) audio path
            if audio_paths:
                return next(iter(audio_paths.values()))
            return None

        except Exception as e:
            print(f"Error rendering audio for solution {solution_id}: {e}")
            return None

    def _find_existing_audio_file(self, solution_id: str, parameters: Dict[str, Any]) -> Optional[str]:
        """Find and register an existing audio file for testing purposes.

        Args:
            solution_id: Unique solution identifier
            parameters: Solution parameters

        Returns:
            Audio file ID if found and registered, None otherwise
        """
        try:
            # Look for existing WAV files in the renders directory
            renders_path = self.reaper_project_path / "renders"
            if not renders_path.exists():
                return None

            # Find any WAV file in the renders directory
            wav_files = list(renders_path.glob("**/untitled.wav"))
            if not wav_files:
                return None

            # Use the first available WAV file
            audio_path = wav_files[0]

            # Create a unique audio file ID
            audio_file_id = str(uuid.uuid4())

            # Register it in the database
            self.db.add_audio_file(
                file_id=audio_file_id,
                filename=audio_path.name,
                filepath=str(audio_path),
                metadata={
                    'solution_id': solution_id,
                    'parameters': parameters,
                    'note': 'Using existing rendered audio for testing'
                }
            )

            return audio_file_id

        except Exception as e:
            print(f"Error finding existing audio file: {e}")
            return None

    def _generate_comparison_pairs(self, solutions: List[Dict[str, Any]]) -> List[str]:
        """Generate pairwise comparison pairs for solutions.

        Args:
            solutions: List of solution information

        Returns:
            List of comparison IDs
        """
        comparison_ids = []

        # Generate all possible pairs (for now - could use more sophisticated strategies)
        for i in range(len(solutions)):
            for j in range(i + 1, len(solutions)):
                comparison_id = str(uuid.uuid4())

                self.db.add_comparison(
                    comparison_id=comparison_id,
                    solution_a_id=solutions[i]['id'],
                    solution_b_id=solutions[j]['id']
                )

                comparison_ids.append(comparison_id)

        return comparison_ids

    def get_next_comparison(self) -> Optional[Dict[str, Any]]:
        """Get next comparison pair for user evaluation.

        Returns:
            Comparison information with audio files
        """
        pending_comparisons = self.db.get_pending_comparisons(limit=1)
        if not pending_comparisons:
            return None

        comparison = pending_comparisons[0]

        # Get solution details
        solution_a = self.db.get_solution(comparison['solution_a_id'])
        solution_b = self.db.get_solution(comparison['solution_b_id'])

        # Get audio file details
        audio_a = None
        audio_b = None

        if solution_a and solution_a['audio_file_id']:
            audio_a = self.db.get_audio_file(solution_a['audio_file_id'])

        if solution_b and solution_b['audio_file_id']:
            audio_b = self.db.get_audio_file(solution_b['audio_file_id'])

        return {
            'comparison_id': comparison['id'],
            'solution_a': {
                'id': solution_a['id'] if solution_a else None,
                'parameters': solution_a['parameters'] if solution_a else None,
                'audio_file': audio_a
            },
            'solution_b': {
                'id': solution_b['id'] if solution_b else None,
                'parameters': solution_b['parameters'] if solution_b else None,
                'audio_file': audio_b
            }
        }

    def submit_comparison_preference(self, comparison_id: str, preference: str,
                                   confidence: float, notes: Optional[str] = None) -> bool:
        """Submit user preference for comparison.

        Args:
            comparison_id: Comparison ID
            preference: 'a' or 'b'
            confidence: Confidence level (0.0 to 1.0)
            notes: Optional notes

        Returns:
            Success status
        """
        success = self.db.submit_comparison_preference(
            comparison_id=comparison_id,
            preference=preference,
            confidence=confidence,
            notes=notes
        )

        if success:
            # Update Bradley-Terry calculations
            self._update_bt_calculations()

        return success

    def _update_bt_calculations(self):
        """Update Bradley-Terry model calculations based on current comparisons."""
        # This is a simplified version - in production, you'd use the full choix library
        # For now, we'll implement a basic strength calculation

        # Get all completed comparisons
        with self.db.get_connection() as conn:
            comparisons = conn.execute(
                "SELECT * FROM comparisons WHERE preference IS NOT NULL"
            ).fetchall()

        if not comparisons:
            return

        # Simple win-loss ratio calculation (placeholder for full BT model)
        solution_stats = {}

        for comp in comparisons:
            a_id = comp['solution_a_id']
            b_id = comp['solution_b_id']

            if a_id not in solution_stats:
                solution_stats[a_id] = {'wins': 0, 'losses': 0}
            if b_id not in solution_stats:
                solution_stats[b_id] = {'wins': 0, 'losses': 0}

            if comp['preference'] == 'a':
                solution_stats[a_id]['wins'] += 1
                solution_stats[b_id]['losses'] += 1
            else:
                solution_stats[b_id]['wins'] += 1
                solution_stats[a_id]['losses'] += 1

        # Calculate and store strengths
        for solution_id, stats in solution_stats.items():
            total_comparisons = stats['wins'] + stats['losses']
            if total_comparisons > 0:
                strength = stats['wins'] / total_comparisons
                self.db.update_bt_strength(solution_id, strength)

    def get_population_with_strengths(self, population_id: str) -> Dict[str, Any]:
        """Get population with current Bradley-Terry strengths.

        Args:
            population_id: Population ID

        Returns:
            Population information with BT strengths
        """
        solutions = self.db.get_solutions_for_population(population_id)
        bt_strengths = self.db.get_bt_strengths_for_population(population_id)

        # Merge strengths with solutions
        strength_map = {bt['solution_id']: bt for bt in bt_strengths}

        for solution in solutions:
            solution_id = solution['id']
            if solution_id in strength_map:
                solution['bt_strength'] = strength_map[solution_id]
            else:
                solution['bt_strength'] = None

        return {
            'population_id': population_id,
            'solutions': solutions
        }

    def get_session_populations(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all populations for a session.

        Args:
            session_id: Session ID

        Returns:
            List of population information
        """
        populations = self.db.get_populations_for_session(session_id)

        # Add solution counts for each population
        for pop in populations:
            solutions = self.db.get_solutions_for_population(pop['id'])
            pop['solution_count'] = len(solutions)

        return populations

    def get_comparison_stats(self) -> Dict[str, Any]:
        """Get current comparison statistics."""
        return self.db.get_comparison_stats()
