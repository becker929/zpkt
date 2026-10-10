"""Constants and configuration for AutoDAW application."""

from pathlib import Path

# Database configuration
DEFAULT_DB_PATH = Path("autodaw.db")

# API configuration
DEFAULT_API_HOST = "0.0.0.0"
DEFAULT_API_PORT = 8000
FRONTEND_URLS = ["http://localhost:3000", "http://127.0.0.1:3000"]

# GA configuration with strict validation
DEFAULT_POPULATION_SIZE = 8
MIN_POPULATION_SIZE = 2
MAX_POPULATION_SIZE = 100
DEFAULT_TARGET_FREQUENCY = 440.0
MIN_TARGET_FREQUENCY = 0.1  # 0.1 Hz minimum
MAX_TARGET_FREQUENCY = 20000.0  # 20 kHz maximum

# Session validation
MIN_SESSION_NAME_LENGTH = 1
MAX_SESSION_NAME_LENGTH = 200
MAX_NOTES_LENGTH = 2000

# JSI configuration
DEFAULT_ORACLE_NOISE_LEVEL = 0.0  # Use real user feedback
DEFAULT_SHOW_LIVE_RANKING = False  # Disable for web interface

# Audio configuration
DEFAULT_AUDIO_FORMAT = "wav"
SUPPORTED_AUDIO_FORMATS = ["wav", "mp3", "flac"]

# File paths
REAPER_PROJECT_PATH = Path(__file__).parent.parent.parent / "reaper"
RENDERS_PATH = REAPER_PROJECT_PATH / "renders"

# Session configuration
SESSION_NAME_PREFIX = "web_session"
DEFAULT_SESSION_STATUS = "active"

# Bradley-Terry configuration
BT_CONFIDENCE_THRESHOLD = 0.7
BT_MODERATE_CONFIDENCE_THRESHOLD = 0.5

# Comparison configuration
DEFAULT_CONFIDENCE = 0.5
MIN_CONFIDENCE = 0.0
MAX_CONFIDENCE = 1.0

# UI configuration
STATS_REFRESH_INTERVAL_MS = 30000  # 30 seconds
DEFAULT_COMPARISON_LIMIT = 10

# Error messages
ERROR_SESSION_NOT_FOUND = "Session not found"
ERROR_POPULATION_NOT_FOUND = "Population not found"
ERROR_COMPARISON_NOT_FOUND = "Comparison not found"
ERROR_AUDIO_FILE_NOT_FOUND = "Audio file not found"
ERROR_INVALID_PREFERENCE = "Preference must be 'a' or 'b'"
ERROR_INVALID_CONFIDENCE = "Confidence must be between 0.0 and 1.0"
ERROR_REAPER_PROJECT_NOT_FOUND = "REAPER project not found"
ERROR_AUDIO_RENDER_FAILED = "Failed to render audio"

# Success messages
SUCCESS_SESSION_CREATED = "Session created successfully"
SUCCESS_POPULATION_INITIALIZED = "Population initialized successfully"
SUCCESS_PREFERENCE_RECORDED = "Preference recorded successfully"
