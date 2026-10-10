"""Database models and connection management for AutoDAW."""

import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
import json
from contextlib import contextmanager


class Database:
    """SQLite database manager for AutoDAW."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file. If None, uses default location.
        """
        if db_path is None:
            db_path = Path("autodaw.db")

        self.db_path = db_path
        self._init_database()

    def _init_database(self):
        """Initialize database tables if they don't exist."""
        with self.get_connection() as conn:
            conn.executescript("""
                -- Audio files table
                CREATE TABLE IF NOT EXISTS audio_files (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    filepath TEXT NOT NULL,
                    duration REAL,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- GA populations table
                CREATE TABLE IF NOT EXISTS populations (
                    id TEXT PRIMARY KEY,
                    generation INTEGER NOT NULL,
                    session_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- GA solutions/individuals table
                CREATE TABLE IF NOT EXISTS solutions (
                    id TEXT PRIMARY KEY,
                    population_id TEXT NOT NULL,
                    parameters TEXT NOT NULL,  -- JSON encoded parameters
                    fitness REAL,
                    rank INTEGER,
                    audio_file_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (population_id) REFERENCES populations (id),
                    FOREIGN KEY (audio_file_id) REFERENCES audio_files (id)
                );

                -- Pairwise comparisons table
                CREATE TABLE IF NOT EXISTS comparisons (
                    id TEXT PRIMARY KEY,
                    solution_a_id TEXT NOT NULL,
                    solution_b_id TEXT NOT NULL,
                    preference TEXT,  -- 'a', 'b', or NULL
                    confidence REAL,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (solution_a_id) REFERENCES solutions (id),
                    FOREIGN KEY (solution_b_id) REFERENCES solutions (id)
                );

                -- Bradley-Terry model strengths table
                CREATE TABLE IF NOT EXISTS bt_strengths (
                    id TEXT PRIMARY KEY,
                    solution_id TEXT NOT NULL,
                    strength REAL NOT NULL,
                    confidence_interval_lower REAL,
                    confidence_interval_upper REAL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (solution_id) REFERENCES solutions (id)
                );

                -- GA sessions table
                CREATE TABLE IF NOT EXISTS ga_sessions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    target_frequency REAL,
                    population_size INTEGER NOT NULL,
                    current_generation INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'active',  -- 'active', 'paused', 'completed'
                    config TEXT,  -- JSON encoded configuration
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- Indexes for performance
                CREATE INDEX IF NOT EXISTS idx_solutions_population ON solutions (population_id);
                CREATE INDEX IF NOT EXISTS idx_comparisons_solutions ON comparisons (solution_a_id, solution_b_id);
                CREATE INDEX IF NOT EXISTS idx_bt_strengths_solution ON bt_strengths (solution_id);
                CREATE INDEX IF NOT EXISTS idx_populations_session ON populations (session_id);
            """)

    @contextmanager
    def get_connection(self):
        """Get database connection context manager."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row  # Enable column access by name
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # Audio files operations
    def add_audio_file(self, file_id: str, filename: str, filepath: str,
                      duration: Optional[float] = None, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Add audio file record to database."""
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO audio_files (id, filename, filepath, duration, metadata) VALUES (?, ?, ?, ?, ?)",
                (file_id, filename, filepath, duration, json.dumps(metadata) if metadata else None)
            )
        return True

    def get_audio_file(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get audio file by ID."""
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM audio_files WHERE id = ?", (file_id,)).fetchone()
            if row:
                result = dict(row)
                if result['metadata']:
                    result['metadata'] = json.loads(result['metadata'])
                return result
        return None

    def list_audio_files(self) -> List[Dict[str, Any]]:
        """List all audio files."""
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM audio_files ORDER BY created_at DESC").fetchall()
            results = []
            for row in rows:
                result = dict(row)
                if result['metadata']:
                    result['metadata'] = json.loads(result['metadata'])
                results.append(result)
            return results

    # GA sessions operations
    def create_ga_session(self, session_id: str, name: str, target_frequency: Optional[float] = None,
                         population_size: int = 8, config: Optional[Dict[str, Any]] = None) -> bool:
        """Create new GA session."""
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO ga_sessions (id, name, target_frequency, population_size, config) VALUES (?, ?, ?, ?, ?)",
                (session_id, name, target_frequency, population_size, json.dumps(config) if config else None)
            )
        return True

    def get_ga_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get GA session by ID."""
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM ga_sessions WHERE id = ?", (session_id,)).fetchone()
            if row:
                result = dict(row)
                if result['config']:
                    result['config'] = json.loads(result['config'])
                return result
        return None

    def update_ga_session_generation(self, session_id: str, generation: int) -> bool:
        """Update current generation for GA session."""
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE ga_sessions SET current_generation = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (generation, session_id)
            )
        return True

    # Populations operations
    def add_population(self, population_id: str, session_id: str, generation: int) -> bool:
        """Add population record."""
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO populations (id, session_id, generation) VALUES (?, ?, ?)",
                (population_id, session_id, generation)
            )
        return True

    def get_populations_for_session(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all populations for a session."""
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM populations WHERE session_id = ? ORDER BY generation DESC",
                (session_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    # Solutions operations
    def add_solution(self, solution_id: str, population_id: str, parameters: Dict[str, Any],
                    fitness: Optional[float] = None, rank: Optional[int] = None,
                    audio_file_id: Optional[str] = None) -> bool:
        """Add solution record."""
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO solutions (id, population_id, parameters, fitness, rank, audio_file_id) VALUES (?, ?, ?, ?, ?, ?)",
                (solution_id, population_id, json.dumps(parameters), fitness, rank, audio_file_id)
            )
        return True

    def get_solutions_for_population(self, population_id: str) -> List[Dict[str, Any]]:
        """Get all solutions for a population."""
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM solutions WHERE population_id = ? ORDER BY rank ASC",
                (population_id,)
            ).fetchall()
            results = []
            for row in rows:
                result = dict(row)
                result['parameters'] = json.loads(result['parameters'])
                results.append(result)
            return results

    def get_solution(self, solution_id: str) -> Optional[Dict[str, Any]]:
        """Get solution by ID."""
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM solutions WHERE id = ?", (solution_id,)).fetchone()
            if row:
                result = dict(row)
                result['parameters'] = json.loads(result['parameters'])
                return result
        return None

    # Comparisons operations
    def add_comparison(self, comparison_id: str, solution_a_id: str, solution_b_id: str) -> bool:
        """Add comparison record."""
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO comparisons (id, solution_a_id, solution_b_id) VALUES (?, ?, ?)",
                (comparison_id, solution_a_id, solution_b_id)
            )
        return True

    def submit_comparison_preference(self, comparison_id: str, preference: str,
                                   confidence: float, notes: Optional[str] = None) -> bool:
        """Submit preference for comparison."""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE comparisons SET preference = ?, confidence = ?, notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (preference, confidence, notes, comparison_id)
            )
            return cursor.rowcount > 0

    def get_pending_comparisons(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get pending comparisons (without preferences)."""
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM comparisons WHERE preference IS NULL ORDER BY created_at ASC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    def get_comparison(self, comparison_id: str) -> Optional[Dict[str, Any]]:
        """Get comparison by ID."""
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM comparisons WHERE id = ?", (comparison_id,)).fetchone()
            return dict(row) if row else None

    # Bradley-Terry strengths operations
    def update_bt_strength(self, solution_id: str, strength: float,
                          ci_lower: Optional[float] = None, ci_upper: Optional[float] = None) -> bool:
        """Update Bradley-Terry strength for solution."""
        with self.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO bt_strengths
                   (id, solution_id, strength, confidence_interval_lower, confidence_interval_upper, updated_at)
                   VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (f"bt_{solution_id}", solution_id, strength, ci_lower, ci_upper)
            )
        return True

    def get_bt_strengths_for_population(self, population_id: str) -> List[Dict[str, Any]]:
        """Get Bradley-Terry strengths for all solutions in a population."""
        with self.get_connection() as conn:
            rows = conn.execute(
                """SELECT bt.*, s.population_id FROM bt_strengths bt
                   JOIN solutions s ON bt.solution_id = s.id
                   WHERE s.population_id = ?
                   ORDER BY bt.strength DESC""",
                (population_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    # Statistics operations
    def get_comparison_stats(self) -> Dict[str, Any]:
        """Get comparison statistics."""
        with self.get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0]
            completed = conn.execute("SELECT COUNT(*) FROM comparisons WHERE preference IS NOT NULL").fetchone()[0]

            # Preference distribution
            prefs = conn.execute(
                "SELECT preference, COUNT(*) FROM comparisons WHERE preference IS NOT NULL GROUP BY preference"
            ).fetchall()

            # Average confidence
            avg_conf = conn.execute(
                "SELECT AVG(confidence) FROM comparisons WHERE confidence IS NOT NULL"
            ).fetchone()[0] or 0

            return {
                "total_comparisons": total,
                "completed_comparisons": completed,
                "remaining_comparisons": total - completed,
                "preference_distribution": {row[0]: row[1] for row in prefs},
                "average_confidence": round(avg_conf, 2)
            }
