"""Tests for the config helper (get_setting)."""

import os
from unittest.mock import patch

import pytest

from invoice_extractor.config import get_setting


class TestGetSetting:
    def test_reads_from_env(self):
        with patch.dict(os.environ, {"LLM_MODEL": "test-model"}):
            assert get_setting("LLM_MODEL") == "test-model"

    def test_returns_default_when_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            assert get_setting("NONEXISTENT_KEY") is None

    def test_returns_explicit_default(self):
        with patch.dict(os.environ, {}, clear=True):
            assert get_setting("NONEXISTENT_KEY", "fallback") == "fallback"

    def test_env_takes_precedence_over_default(self):
        with patch.dict(os.environ, {"MY_KEY": "from-env"}):
            assert get_setting("MY_KEY", "from-default") == "from-env"

    def test_no_raise_without_secrets(self):
        with patch.dict(os.environ, {}, clear=True):
            result = get_setting("ANYTHING")
            assert result is None
