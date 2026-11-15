"""Shared pytest fixtures for core and module tests.

``client`` runs every test that uses it twice: against the core alone and with
all modules loaded. A module that breaks core behaviour therefore fails the
core suite, not just its own tests.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(params=["none", "all"], ids=["core-only", "all-modules"])
def client(request, tmp_path):
    """Test client on a fresh database; parametrised over core-only and all modules."""
    return TestClient(create_app(tmp_path / "test.db", modules=request.param))


@pytest.fixture
def make_client(tmp_path):
    """Factory: ``make_client(modules="activity_map")`` -> TestClient on a fresh database."""

    def make(modules: str = "all", modules_dir=None) -> TestClient:
        return TestClient(create_app(tmp_path / "test.db", modules=modules, modules_dir=modules_dir))

    return make
