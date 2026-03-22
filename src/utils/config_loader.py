"""Shared path-resolving helpers for venue configuration files.

Provides utilities for loading and validating YAML-based venue
configuration, resolving relative paths against the repository root,
and exposing the result as an immutable, cached dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from utils.repo_paths import REPO_ROOT, VENUE_CONFIG_ROOT


def _resolve_path(path_value: str) -> Path:
    """Resolve a path string relative to the repository root.

    If *path_value* is already absolute it is returned unchanged;
    otherwise it is joined to ``REPO_ROOT``.

    @param path_value: Filesystem path as a string (absolute or relative).
    @return: Resolved absolute ``Path``.
    """
    path = Path(path_value)
    if path.is_absolute():
        return path  # Already absolute – nothing to resolve
    # Treat as relative to the repository root
    return REPO_ROOT / path


def _require_string(data: dict[str, Any], key: str, *, context: str) -> str:
    """Extract a required string value from *data*.

    @param data: Mapping to look up the key in.
    @param key: Key whose value must be a ``str``.
    @param context: Human-readable label used in the error message on failure.
    @return: The string value associated with *key*.
    @raises ValueError: If *key* is missing or its value is not a string.
    """
    value = data.get(key)
    # None (missing key) or wrong type both trigger the error
    if not isinstance(value, str):
        raise ValueError(f"{context} is missing a string {key!r}.")
    return value


def _require_mapping(data: dict[str, Any], key: str, *, context: str) -> dict[str, Any]:
    """Extract a required mapping (dict) value from *data*.

    @param data: Mapping to look up the key in.
    @param key: Key whose value must be a ``dict``.
    @param context: Human-readable label used in the error message on failure.
    @return: The ``dict`` value associated with *key*.
    @raises ValueError: If *key* is missing or its value is not a mapping.
    """
    value = data.get(key)
    # None (missing key) or wrong type both trigger the error
    if not isinstance(value, dict):
        raise ValueError(f"{context} is missing a mapping {key!r}.")
    return value


# frozen=True makes instances immutable and hashable (required for lru_cache)
@dataclass(frozen=True)
class VenueConfig:
    """Typed, immutable representation of a venue configuration file.

    Attributes:
        api_endpoint: Base URL for the venue's REST API.
        raw_root: Absolute path to the venue's top-level raw data directory.
        historical_data_folder: Absolute path to the historical data directory.
        live_data_folder: Absolute path to the live/streaming data directory.
        raw: The full, unparsed configuration dictionary as loaded from YAML.
    """

    api_endpoint: str               # Base URL for the venue's REST API
    raw_root: Path                  # top-level raw data directory for this venue
    historical_data_folder: Path    # sub-folder holding historical datasets
    live_data_folder: Path          # sub-folder holding live / streaming data
    raw: dict[str, Any]             # complete YAML dict preserved for ad-hoc access

    @classmethod
    @cache  # Avoids re-reading YAML on repeated calls
    def load(cls, venue: str) -> VenueConfig:
        """Load and cache the configuration for a given venue.

        The YAML file is read from ``VENUE_CONFIG_ROOT/<venue>.yaml``
        (case-insensitive). Results are cached so repeated calls with the
        same *venue* value return the identical instance.

        @param venue: Venue identifier (e.g. ``"venue_a"``, ``"venue_b"``).
        @return: A frozen ``VenueConfig`` instance with all paths resolved.
        @raises FileNotFoundError: If the YAML file does not exist.
        @raises ValueError: If the YAML content is not a valid venue config.
        """
        # Normalise to lowercase so e.g. "Venue_A" and
        # "venue_a" resolve to the same file
        path = VENUE_CONFIG_ROOT / f"{venue.lower()}.yaml"

        # Read and parse the YAML file into a Python dict
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Venue config for {venue!r} must parse to a mapping.")

        # Prefix for any validation errors that follow
        ctx = f"Venue config for {venue!r}"

        # Pull out the required "folder_structure" section
        fs = _require_mapping(data, "folder_structure", context=ctx)

        # Build the dataclass – each path is validated then resolved to absolute
        return cls(
            api_endpoint=_require_string(data, "api_endpoint", context=ctx),
            raw_root=_resolve_path(
                _require_string(fs, "raw_root", context=f"{ctx} folder_structure"),
            ),
            historical_data_folder=_resolve_path(
                _require_string(
                    fs,
                    "historical_data_folder",
                    context=f"{ctx} folder_structure",
                ),
            ),
            live_data_folder=_resolve_path(
                _require_string(
                    fs,
                    "live_data_folder",
                    context=f"{ctx} folder_structure",
                ),
            ),
            raw=data,
        )
