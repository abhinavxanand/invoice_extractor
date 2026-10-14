"""Unified config: reads os.environ, never imports streamlit."""

from __future__ import annotations

import os


def get_setting(key: str, default: str | None = None) -> str | None:
    """Return env var *key*, falling back to *default*."""
    return os.environ.get(key, default)
