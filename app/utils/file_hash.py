"""File hash utilities for caching."""

from __future__ import annotations

import hashlib


def compute_file_hash(file_bytes: bytes) -> str:
    """Compute MD5 hash of file bytes for cache key generation.

    Args:
        file_bytes: Raw file bytes to hash

    Returns:
        MD5 hex digest string (32 characters)

    Example:
        >>> data = b"column1,column2\n1,2\n3,4"
        >>> compute_file_hash(data)
        'a1b2c3d4...'
    """
    return hashlib.md5(file_bytes).hexdigest()
