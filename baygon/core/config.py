"""Config Loader.

Reads ``baygon.yaml``, validates its structure and builds the in-memory
configuration. An invalid file forbids execution (ConfigError).

``baygon.yaml`` is the single source of truth of a project: nothing that
can be declared there may be hard-coded in Baygon.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from baygon.core.errors import ConfigError

SUPPORTED_SCHEMA_VERSIONS = (1,)
REQUIRED_ENVIRONMENTS = ("development", "staging", "production")

# Top-level sections of the schema. Only these keys are accepted.
KNOWN_SECTIONS = (
    "version",
    "project",
    "providers",
    "environments",
    "workspaces",
    "ai",
    "observability",
    "commands",
    "permissions",
    "metadata",
)


@dataclass
class ProviderConfig:
    """One provider declaration: a name, a type and a configuration."""

    name: str
    type: str
    plugin: str
    default: bool = False
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class BaygonConfig:
    version: int
    project: dict[str, Any]
    providers: list[ProviderConfig]
    environments: dict[str, dict[str, Any]]
    workspaces: dict[str, Any] = field(default_factory=dict)
    ai: dict[str, Any] = field(default_factory=dict)
    observability: dict[str, Any] = field(default_factory=dict)
    commands: dict[str, Any] = field(default_factory=dict)
    permissions: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    @property
    def project_name(self) -> str:
        return str(self.project["name"])

    def is_allowed(self, operation: str) -> bool:
        """An operation is allowed only when explicitly declared true.

        Defaults that could create ambiguity are forbidden, so an
        undeclared permission means "not allowed".
        """
        return bool(self.permissions.get(operation, False))


def _require(mapping: dict[str, Any], key: str, kind: type, where: str) -> Any:
    if key not in mapping or mapping[key] is None:
        raise ConfigError(f"Missing required key {key!r} in {where}")
    value = mapping[key]
    if not isinstance(value, kind):
        raise ConfigError(
            f"Key {key!r} in {where} must be of type {kind.__name__}, "
            f"got {type(value).__name__}"
        )
    return value


def _parse_providers(raw: dict[str, Any]) -> list[ProviderConfig]:
    providers: list[ProviderConfig] = []
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            raise ConfigError(f"Provider {name!r} must be a mapping")
        type_ = _require(entry, "type", str, f"provider {name!r}")
        plugin = _require(entry, "plugin", str, f"provider {name!r}")
        default = bool(entry.get("default", False))
        options = entry.get("options", {}) or {}
        if not isinstance(options, dict):
            raise ConfigError(f"Provider {name!r}: 'options' must be a mapping")
        providers.append(
            ProviderConfig(name=name, type=type_, plugin=plugin, default=default, options=options)
        )
    return providers


def load_config(path: str | Path) -> BaygonConfig:
    """Load and validate a ``baygon.yaml`` file."""
    file = Path(path)
    if file.is_dir():
        file = file / "baygon.yaml"
    if not file.exists():
        raise ConfigError(f"Configuration file not found: {file}")

    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {file}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{file} must contain a YAML mapping")

    unknown = set(raw) - set(KNOWN_SECTIONS)
    if unknown:
        raise ConfigError(f"Unknown top-level section(s): {', '.join(sorted(unknown))}")

    version = _require(raw, "version", int, str(file))
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ConfigError(
            f"Unsupported schema version {version}; "
            f"supported: {', '.join(map(str, SUPPORTED_SCHEMA_VERSIONS))}"
        )

    project = _require(raw, "project", dict, str(file))
    _require(project, "name", str, "section 'project'")

    providers_raw = _require(raw, "providers", dict, str(file))
    providers = _parse_providers(providers_raw)

    environments = _require(raw, "environments", dict, str(file))
    missing = [env for env in REQUIRED_ENVIRONMENTS if env not in environments]
    if missing:
        raise ConfigError(f"Missing required environment(s): {', '.join(missing)}")
    environments = {name: (value or {}) for name, value in environments.items()}
    for name, value in environments.items():
        if not isinstance(value, dict):
            raise ConfigError(f"Environment {name!r} must be a mapping")

    return BaygonConfig(
        version=version,
        project=project,
        providers=providers,
        environments=environments,
        workspaces=raw.get("workspaces") or {},
        ai=raw.get("ai") or {},
        observability=raw.get("observability") or {},
        commands=raw.get("commands") or {},
        permissions=raw.get("permissions") or {},
        metadata=raw.get("metadata") or {},
        path=file,
    )
