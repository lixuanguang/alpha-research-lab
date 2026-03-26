"""HTTP download and request utilities with retry and backoff."""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# JSON requests
# ---------------------------------------------------------------------------


def fetch_json(req: Request, *, retries: int = 5, timeout: int = 180) -> Any:
    """Send a request and return decoded JSON, with exponential backoff on failure."""
    for attempt in range(retries):
        try:
            with urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            if attempt + 1 == retries:
                raise RuntimeError(f"Request to {req.full_url} failed after {retries} attempts") from e
            time.sleep(min(20, 2 ** (attempt + 1)))


def paginate_json(build_request: Callable[[Any], Request], next_state: Callable[[Any, Any], Any | None],
                  state: Any, *, retries: int = 5, timeout: int = 180, pause: float = 0.0) -> Iterator[Any]:
    """Paginate a JSON API, yielding each decoded page response.

    Delegates request building and stop logic to callbacks so callers
    control deduplication, accumulation, and termination conditions.
    """
    while True:
        data = fetch_json(build_request(state), retries=retries, timeout=timeout)
        yield data
        state = next_state(data, state)
        if state is None:
            break
        if pause > 0:
            time.sleep(pause)

# ---------------------------------------------------------------------------
# File downloads
# ---------------------------------------------------------------------------


def download_file(url: str, target: Path, *, user_agent: str, retries: int = 5) -> int:
    """Download a file to target path with atomic write and exponential backoff.

    Skips the download and returns the existing size if target already exists.
    Writes to a .part temp file and atomically renames on success.
    """
    if target.exists():
        return target.stat().st_size

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")

    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": user_agent})
            with urlopen(req, timeout=300) as r, tmp.open("wb") as f:
                shutil.copyfileobj(r, f)
            break
        except Exception as e:
            tmp.unlink(missing_ok=True)
            if attempt + 1 == retries:
                raise RuntimeError(f"Failed to download {url} after {retries} attempts") from e
            time.sleep(min(20, 2 ** (attempt + 1)))

    tmp.replace(target)
    return target.stat().st_size
