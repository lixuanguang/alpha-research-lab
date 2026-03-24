"""Shared YAML config loaders."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from utils.path_utils import REPO_ROOT, UTILS_CONFIG_ROOT, VENUE_CONFIG_ROOT


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must parse to a mapping.")
    return data


@dataclass(frozen=True)
class DateUtilsConfig:
    period_specs: dict[str, dict[str, Any]]

    @classmethod
    @cache
    def load(cls) -> DateUtilsConfig:
        data = _load_yaml(UTILS_CONFIG_ROOT / "date_utils_config.yaml")
        specs: dict[str, dict[str, Any]] = {}
        for name, entry in data["period_specs"].items():
            spec = {"pattern": entry["pattern"], "format": entry["format"]}
            specs[name] = spec
            for alias in entry.get("aliases", []):
                specs[alias] = spec
        return cls(period_specs=specs)


@dataclass(frozen=True)
class VenueConfig:
    api_endpoint: str
    raw_root: Path
    historical_data_folder: Path
    live_data_folder: Path
    raw: dict[str, Any]

    @classmethod
    @cache
    def load(cls, venue: str) -> VenueConfig:
        data = _load_yaml(VENUE_CONFIG_ROOT / f"{venue.lower()}.yaml")
        fs = data["folder_structure"]
        resolve = lambda p: Path(p) if Path(p).is_absolute() else REPO_ROOT / p
        return cls(
            api_endpoint=data["api_endpoint"],
            raw_root=resolve(fs["raw_root"]),  # type: ignore[no-untyped-call]
            historical_data_folder=resolve(fs["historical_data_folder"]),  # type: ignore[no-untyped-call]
            live_data_folder=resolve(fs["live_data_folder"]),  # type: ignore[no-untyped-call]
            raw=data,
        )
