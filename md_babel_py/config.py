"""Configuration loading for md-babel-py."""

import json
import logging
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from .exceptions import ConfigError

logger = logging.getLogger(__name__)


def _load_default_config() -> dict[str, Any] | None:
    """Load bundled default config."""
    try:
        ref = resources.files("md_babel_py").joinpath("default_config.json")
        content = ref.read_text()
        result: dict[str, Any] = json.loads(content)
        return result
    except (TypeError, FileNotFoundError, json.JSONDecodeError):
        return None


@dataclass
class SessionConfig:
    """Session configuration for a language.

    Attributes:
        command: Command to start the REPL (e.g., ["python3", "-i"]).
        marker: Optional custom marker command. If not set, uses built-in default.
        prompts: Optional list of REPL prompt patterns to strip from output.
        protocol: Communication protocol - "json" for structured JSON I/O,
            "marker" for traditional REPL with end markers.
    """
    command: list[str]
    marker: str | None = None
    prompts: list[str] = field(default_factory=list)
    protocol: str = "marker"  # "json" or "marker"


@dataclass
class EvaluatorConfig:
    """Configuration for a code block evaluator.

    Attributes:
        path: Path to the executable.
        default_arguments: Arguments to pass to the executable.
        session: Optional session configuration for persistent REPL execution.
        input_extension: File extension for temp input file (e.g., ".scad").
            If set, code is written to a temp file instead of stdin.
            Use {input_file} placeholder in defaultArguments.
        default_params: Default parameter values for {key} substitution.
            Can be overridden by params in code block info string.
        prefix: String to prepend to code before execution.
        suffix: String to append to code before execution.
    """
    path: str
    default_arguments: list[str]
    session: SessionConfig | None = None
    input_extension: str | None = None
    default_params: dict[str, str] = field(default_factory=dict)
    prefix: str = ""
    suffix: str = ""


@dataclass
class Config:
    """Full configuration.

    Attributes:
        evaluators: Mapping of language names to their evaluator configurations.
    """
    evaluators: dict[str, EvaluatorConfig]


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from file(s).

    Search order:
    1. Explicit config_path if provided
    2. ./config.json
    3. ~/.config/md-babel/config.json

    Configs are merged, with earlier ones taking precedence.

    Args:
        config_path: Optional explicit path to a config file.

    Returns:
        Merged configuration from all found config files.

    Raises:
        ConfigError: If a config file exists but is invalid.
    """
    configs_to_try: list[Path] = []

    if config_path:
        configs_to_try.append(config_path)

    configs_to_try.extend([
        Path.cwd() / "config.json",
        Path.home() / ".config" / "md-babel" / "config.json",
    ])

    merged_evaluators: dict[str, EvaluatorConfig] = {}

    # Load bundled default config first (lowest precedence)
    default_raw = _load_default_config()
    if default_raw:
        logger.debug("Loading bundled default config")
        try:
            evaluators = _parse_evaluators(default_raw, Path("<default>"))
            merged_evaluators.update(evaluators)
        except Exception as e:
            logger.warning(f"Error parsing bundled config: {e}")

    # Load external configs (higher precedence, processed in reverse order)
    for path in reversed(configs_to_try):
        if path.exists():
            logger.debug(f"Loading config from {path}")
            try:
                raw = json.loads(path.read_text())
            except json.JSONDecodeError as e:
                raise ConfigError(f"Invalid JSON in {path}: {e}") from e

            try:
                evaluators = _parse_evaluators(raw, path)
                merged_evaluators.update(evaluators)
            except ConfigError:
                raise
            except Exception as e:
                raise ConfigError(f"Error parsing {path}: {e}") from e

    return Config(evaluators=merged_evaluators)


def _parse_evaluators(raw: dict[str, Any], config_path: Path) -> dict[str, EvaluatorConfig]:
    """Parse evaluators from raw JSON config.

    Args:
        raw: Parsed JSON configuration.
        config_path: Path to the config file (for error messages).

    Returns:
        Mapping of language names to evaluator configurations.

    Raises:
        ConfigError: If required fields are missing or invalid.
    """
    evaluators: dict[str, EvaluatorConfig] = {}

    if "evaluators" not in raw:
        return evaluators

    if not isinstance(raw["evaluators"], dict):
        raise ConfigError(f"{config_path}: 'evaluators' must be an object")

    code_block_config = raw["evaluators"].get("codeBlock", {})

    if not isinstance(code_block_config, dict):
        raise ConfigError(f"{config_path}: 'evaluators.codeBlock' must be an object")

    for lang, config in code_block_config.items():
        if not isinstance(config, dict):
            raise ConfigError(f"{config_path}: evaluator for '{lang}' must be an object")

        # Validate required fields
        if "path" not in config:
            raise ConfigError(f"{config_path}: evaluator for '{lang}' missing required field 'path'")

        if not isinstance(config["path"], str):
            raise ConfigError(f"{config_path}: evaluator for '{lang}': 'path' must be a string")

        # Validate optional fields
        default_args = config.get("defaultArguments", [])
        if not isinstance(default_args, list):
            raise ConfigError(
                f"{config_path}: evaluator for '{lang}': 'defaultArguments' must be an array"
            )

        # Parse session config if present
        session = None
        if "session" in config:
            session = _parse_session_config(config["session"], lang, config_path)

        # Parse input extension option
        input_ext = config.get("inputExtension")
        if input_ext is not None and not isinstance(input_ext, str):
            raise ConfigError(
                f"{config_path}: evaluator for '{lang}': 'inputExtension' must be a string"
            )

        # Parse default params
        default_params = config.get("defaultParams", {})
        if not isinstance(default_params, dict):
            raise ConfigError(
                f"{config_path}: evaluator for '{lang}': 'defaultParams' must be an object"
            )
        for key, value in default_params.items():
            if not isinstance(value, str):
                raise ConfigError(
                    f"{config_path}: evaluator for '{lang}': "
                    f"'defaultParams.{key}' must be a string"
                )

        # Parse prefix/suffix
        prefix = config.get("prefix", "")
        if not isinstance(prefix, str):
            raise ConfigError(
                f"{config_path}: evaluator for '{lang}': 'prefix' must be a string"
            )
        suffix = config.get("suffix", "")
        if not isinstance(suffix, str):
            raise ConfigError(
                f"{config_path}: evaluator for '{lang}': 'suffix' must be a string"
            )

        evaluators[lang] = EvaluatorConfig(
            path=config["path"],
            default_arguments=default_args,
            session=session,
            input_extension=input_ext,
            default_params=default_params,
            prefix=prefix,
            suffix=suffix,
        )

    return evaluators


def _parse_session_config(
    session_raw: Any,
    lang: str,
    config_path: Path,
) -> SessionConfig:
    """Parse session configuration.

    Args:
        session_raw: Raw session configuration from JSON.
        lang: Language name (for error messages).
        config_path: Path to the config file (for error messages).

    Returns:
        Parsed session configuration.

    Raises:
        ConfigError: If required fields are missing or invalid.
    """
    if not isinstance(session_raw, dict):
        raise ConfigError(f"{config_path}: session config for '{lang}' must be an object")

    if "command" not in session_raw:
        raise ConfigError(
            f"{config_path}: session config for '{lang}' missing required field 'command'"
        )

    command = session_raw["command"]
    if not isinstance(command, list) or not all(isinstance(c, str) for c in command):
        raise ConfigError(
            f"{config_path}: session config for '{lang}': 'command' must be an array of strings"
        )

    if len(command) == 0:
        raise ConfigError(
            f"{config_path}: session config for '{lang}': 'command' must not be empty"
        )

    # Parse optional prompts
    prompts = session_raw.get("prompts", [])
    if not isinstance(prompts, list) or not all(isinstance(p, str) for p in prompts):
        raise ConfigError(
            f"{config_path}: session config for '{lang}': 'prompts' must be an array of strings"
        )

    # Parse protocol
    protocol = session_raw.get("protocol", "marker")
    if protocol not in ("json", "marker"):
        raise ConfigError(
            f"{config_path}: session config for '{lang}': 'protocol' must be 'json' or 'marker'"
        )

    return SessionConfig(
        command=command,
        marker=session_raw.get("marker"),
        prompts=prompts,
        protocol=protocol,
    )


def get_evaluator(config: Config, language: str) -> EvaluatorConfig | None:
    """Get evaluator config for a language.

    Args:
        config: The loaded configuration.
        language: The language to get the evaluator for.

    Returns:
        The evaluator configuration, or None if not configured.
    """
    return config.evaluators.get(language)
