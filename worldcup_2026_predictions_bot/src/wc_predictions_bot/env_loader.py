from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str = ".env", *, override: bool = False) -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if override or key not in os.environ:
            os.environ[key] = value

