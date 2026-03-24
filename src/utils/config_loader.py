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

from utils.path_utils import REPO_ROOT, VENUE_CONFIG_ROOT


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

        fs = data["folder_structure"]

        resolve = lambda p: Path(p) if Path(p).is_absolute() else REPO_ROOT / p

        return cls(
            api_endpoint=data["api_endpoint"],
            raw_root=resolve(fs["raw_root"]),
            historical_data_folder=resolve(fs["historical_data_folder"]),
            live_data_folder=resolve(fs["live_data_folder"]),
            raw=data,
        )
