from __future__ import annotations

import os
from pathlib import Path


def resolve_model_artifact_uri(local_path: Path) -> str:
    backend = os.getenv("MODEL_STORAGE_BACKEND", "local").strip().lower()
    if backend == "local":
        return str(local_path)

    bucket_prefix = os.getenv("MODEL_STORAGE_URI_PREFIX", "")
    if not bucket_prefix:
        return str(local_path)

    return f"{bucket_prefix.rstrip('/')}/{local_path.name}"
