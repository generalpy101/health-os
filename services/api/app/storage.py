"""Object storage abstraction. Local disk now; S3-compatible can slot in later
without touching callers (same ObjectStorage interface)."""

import os
import uuid
from pathlib import Path

STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", str(Path(__file__).resolve().parents[1] / "data" / "photos")))

ALLOWED_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/heic": "heic"}
MAX_BYTES = 15 * 1024 * 1024


def save_photo(user_id: uuid.UUID, content: bytes, content_type: str) -> str:
    ext = ALLOWED_TYPES.get(content_type, "jpg")
    key = f"{user_id}/{uuid.uuid4()}.{ext}"
    path = STORAGE_DIR / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return key


def read_photo(key: str) -> bytes | None:
    path = (STORAGE_DIR / key).resolve()
    if STORAGE_DIR.resolve() not in path.parents:  # path traversal guard
        return None
    return path.read_bytes() if path.exists() else None


def delete_photo(key: str) -> None:
    path = (STORAGE_DIR / key).resolve()
    if STORAGE_DIR.resolve() in path.parents and path.exists():
        path.unlink()
