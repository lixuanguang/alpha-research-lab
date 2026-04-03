"""Shared YAML config loaders."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

def load_yaml(path: Path) -> dict[str, Any]:
    '''
    Load a YAML file and return its contents as a dictionary.
    
    @param path: The path to the YAML file.
    @return: A dictionary containing the contents of the YAML file.
    @raises ValueError: If the YAML file does not parse to a mapping (dictionary).
    '''
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must parse to a mapping.")
    return data
