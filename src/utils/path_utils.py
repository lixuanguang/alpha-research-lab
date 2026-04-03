"""Repository and filesystem path constants."""

from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = _THIS_DIR.parent.parent
CONFIG_ROOT = REPO_ROOT / "config"
UTILS_CONFIG_ROOT = CONFIG_ROOT / "utils"
VENUE_CONFIG_ROOT = CONFIG_ROOT / "venue"
DATA_ROOT = REPO_ROOT / "data"
