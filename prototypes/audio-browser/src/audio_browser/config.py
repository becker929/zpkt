"""Configuration loading.

Roots are read from a TOML file, never hardcoded. A root has a short name used
in reports and a filesystem path that is resolved through symlinks.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_NAME = "config.toml"
DEFAULT_DB_NAME = "audio-browser.db"

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8090
DEFAULT_FRONTEND_PORT = 3100
DEFAULT_CORS_ORIGINS: tuple[str, ...] = (
    "http://localhost:3100",
    "http://127.0.0.1:3100",
)
# Any host on the frontend port. The frontend is reached over Tailscale as well
# as over localhost, and each tailnet address is a different browser origin.
DEFAULT_CORS_ORIGIN_REGEX = r"https?://[^/]+:3100"


class ConfigError(Exception):
    """Raised when a config file is missing or malformed."""


@dataclass(frozen=True, slots=True)
class Root:
    """One directory tree to scan."""

    name: str
    path: Path


@dataclass(frozen=True, slots=True)
class ServerConfig:
    """Where the API listens and which browser origins may call it."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    frontend_port: int = DEFAULT_FRONTEND_PORT
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    cors_origin_regex: str = DEFAULT_CORS_ORIGIN_REGEX


DEFAULT_PROJECTS_DIR = "projects"
DEFAULT_SCHEMAS_DIR = "schemas"
DEFAULT_COLUMN_CAP = 1
DEFAULT_ENCUMBRANCE = 16
BOARD_COLUMNS: tuple[str, ...] = ("stored", "collage", "enrich")


@dataclass(frozen=True, slots=True)
class ProjectsConfig:
    """Where projects live, how many each column holds, and when one is heavy.

    ``cap`` is the one line to change. The default is 1: ``stored`` is the swipe
    lane, and a second uncommitted project there would mean choosing which
    project a sound goes into. A per-column ``caps`` table overrides it for one
    column at a time.

    A cap of 0 is a legitimate setting and means the column is closed. Nothing
    goes into it without an explicit override, and a column that already holds
    something reads as over its limit the moment the board is drawn.

    ``encumbrance`` is the sound count past which a project is marked as
    carrying more material than a track needs. It sits here, beside the caps,
    because it is the same kind of number: friction the server states and the
    interface draws.

    ``schemas_dir`` holds the JSON Schema generated from the Zod declarations in
    ``frontend/lib/project.ts``. Python validates every project file against
    that generated file, so neither language keeps a second copy of the shape.
    """

    dir: Path
    schemas_dir: Path
    stored_cap: int = DEFAULT_COLUMN_CAP
    collage_cap: int = DEFAULT_COLUMN_CAP
    enrich_cap: int = DEFAULT_COLUMN_CAP
    encumbrance: int = DEFAULT_ENCUMBRANCE

    def cap(self, column: str) -> int:
        return int(getattr(self, f"{column}_cap"))


@dataclass(frozen=True, slots=True)
class Config:
    """Everything the CLI and the server need to find the library."""

    db_path: Path
    roots: tuple[Root, ...]
    server: ServerConfig = ServerConfig()
    projects: ProjectsConfig | None = None

    def root(self, name: str) -> Root | None:
        for r in self.roots:
            if r.name == name:
                return r
        return None


def find_config(explicit: Path | None = None) -> Path:
    """Locate the config file.

    Order: the explicit path, then ``config.toml`` in the current directory,
    then ``config.toml`` next to the installed package's project directory.
    """
    if explicit is not None:
        return explicit
    cwd_candidate = Path.cwd() / DEFAULT_CONFIG_NAME
    if cwd_candidate.exists():
        return cwd_candidate
    # src/audio_browser/config.py -> project root
    project_candidate = Path(__file__).resolve().parents[2] / DEFAULT_CONFIG_NAME
    return project_candidate


def load_config(path: Path | None = None) -> Config:
    """Read and validate a config file."""
    config_path = find_config(path)
    if not config_path.exists():
        raise ConfigError(
            f"no config file at {config_path}; copy config.toml.example to config.toml"
        )
    with config_path.open("rb") as fh:
        raw = tomllib.load(fh)
    return parse_config(raw, base_dir=config_path.parent)


def parse_config(raw: dict[str, object], base_dir: Path) -> Config:
    """Turn parsed TOML into a :class:`Config`.

    Relative paths are resolved against ``base_dir``, the directory holding the
    config file.
    """
    db_raw = raw.get("db", DEFAULT_DB_NAME)
    if not isinstance(db_raw, str):
        raise ConfigError("db must be a string")
    db_path = _absolute(Path(db_raw), base_dir)

    roots_raw = raw.get("roots", [])
    if not isinstance(roots_raw, list) or not roots_raw:
        raise ConfigError("config needs at least one [[roots]] entry")

    roots: list[Root] = []
    seen: set[str] = set()
    for entry in roots_raw:
        if not isinstance(entry, dict):
            raise ConfigError("each [[roots]] entry must be a table")
        name = entry.get("name")
        path = entry.get("path")
        if not isinstance(name, str) or not name:
            raise ConfigError("each root needs a non-empty name")
        if not isinstance(path, str) or not path:
            raise ConfigError(f"root {name!r} needs a non-empty path")
        if name in seen:
            raise ConfigError(f"duplicate root name {name!r}")
        seen.add(name)
        # resolve() follows symlinks, so the compost symlink becomes its target.
        resolved = _absolute(Path(path).expanduser(), base_dir).resolve()
        roots.append(Root(name=name, path=resolved))

    return Config(
        db_path=db_path,
        roots=tuple(roots),
        server=_parse_server(raw.get("server")),
        projects=_parse_projects(raw.get("projects"), base_dir),
    )


def default_projects(base_dir: Path) -> ProjectsConfig:
    """Where projects and schemas sit when nothing says otherwise."""
    return ProjectsConfig(
        dir=base_dir / DEFAULT_PROJECTS_DIR,
        schemas_dir=_package_root() / DEFAULT_SCHEMAS_DIR,
    )


def _package_root() -> Path:
    """The project directory, the one holding ``schemas/`` and ``config.toml``."""
    # src/audio_browser/config.py -> project root
    return Path(__file__).resolve().parents[2]


def _parse_projects(raw: object, base_dir: Path) -> ProjectsConfig:
    """Read the optional ``[projects]`` table. Every key has a default."""
    default = default_projects(base_dir)
    if raw is None:
        return default
    if not isinstance(raw, dict):
        raise ConfigError("[projects] must be a table")

    dir_raw = raw.get("dir", DEFAULT_PROJECTS_DIR)
    if not isinstance(dir_raw, str) or not dir_raw:
        raise ConfigError("projects.dir must be a non-empty string")
    schemas_raw = raw.get("schemas", None)
    if schemas_raw is not None and (not isinstance(schemas_raw, str) or not schemas_raw):
        raise ConfigError("projects.schemas must be a non-empty string")

    cap = _cap(raw.get("cap", DEFAULT_COLUMN_CAP), "projects.cap")
    caps_raw = raw.get("caps", {})
    if not isinstance(caps_raw, dict):
        raise ConfigError("projects.caps must be a table of column names to counts")
    unknown = set(caps_raw) - set(BOARD_COLUMNS)
    if unknown:
        raise ConfigError(
            f"projects.caps names {sorted(unknown)!r}, which are not columns; "
            f"the columns are {list(BOARD_COLUMNS)!r}"
        )
    per_column = {
        column: _cap(caps_raw.get(column, cap), f"projects.caps.{column}")
        for column in BOARD_COLUMNS
    }
    encumbrance = _cap(
        raw.get("encumbrance", DEFAULT_ENCUMBRANCE), "projects.encumbrance", "sounds"
    )

    return ProjectsConfig(
        dir=_absolute(Path(dir_raw).expanduser(), base_dir),
        schemas_dir=(
            _absolute(Path(schemas_raw).expanduser(), base_dir)
            if schemas_raw is not None
            else default.schemas_dir
        ),
        stored_cap=per_column["stored"],
        collage_cap=per_column["collage"],
        enrich_cap=per_column["enrich"],
        encumbrance=encumbrance,
    )


def _cap(value: object, label: str, noun: str = "slots") -> int:
    """A cap is a whole number of slots, zero or more.

    Zero closes a column, which is a real setting. A fraction, a negative
    number, or a word is a mistake and is refused rather than rounded: somebody
    editing this is nearly always turning the cap *down*, and a typo in that
    edit must not quietly hand back a looser board than the one they asked for.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{label} must be a whole number of {noun}")
    if value < 0:
        raise ConfigError(f"{label} must be zero or more")
    return value


def _parse_server(raw: object) -> ServerConfig:
    """Read the optional ``[server]`` table. Every key has a default."""
    if raw is None:
        return ServerConfig()
    if not isinstance(raw, dict):
        raise ConfigError("[server] must be a table")

    host = raw.get("host", DEFAULT_HOST)
    if not isinstance(host, str) or not host:
        raise ConfigError("server.host must be a non-empty string")

    port = _port(raw.get("port", DEFAULT_PORT), "server.port")
    frontend_port = _port(
        raw.get("frontend_port", DEFAULT_FRONTEND_PORT), "server.frontend_port"
    )

    origins_raw = raw.get("cors_origins")
    if origins_raw is None:
        origins = tuple(
            o.replace(f":{DEFAULT_FRONTEND_PORT}", f":{frontend_port}")
            for o in DEFAULT_CORS_ORIGINS
        )
    elif isinstance(origins_raw, list) and all(
        isinstance(o, str) for o in origins_raw
    ):
        origins = tuple(str(o) for o in origins_raw)
    else:
        raise ConfigError("server.cors_origins must be a list of strings")

    regex_raw = raw.get("cors_origin_regex")
    if regex_raw is None:
        regex = DEFAULT_CORS_ORIGIN_REGEX.replace(
            f":{DEFAULT_FRONTEND_PORT}", f":{frontend_port}"
        )
    elif isinstance(regex_raw, str):
        regex = regex_raw
    else:
        raise ConfigError("server.cors_origin_regex must be a string")

    return ServerConfig(
        host=host,
        port=port,
        frontend_port=frontend_port,
        cors_origins=origins,
        cors_origin_regex=regex,
    )


def _port(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{label} must be an integer")
    if not 1 <= value <= 65535:
        raise ConfigError(f"{label} must be between 1 and 65535")
    return value


def _absolute(path: Path, base_dir: Path) -> Path:
    return path if path.is_absolute() else (base_dir / path)
