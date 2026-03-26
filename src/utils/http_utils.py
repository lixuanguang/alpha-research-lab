"""HTTP download utilities."""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from urllib.request import Request, urlopen


def download_file(url: str, target: Path, *, user_agent: str, retries: int = 5) -> int:
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
