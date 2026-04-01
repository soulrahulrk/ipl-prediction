"""Initial test configuration and fixtures."""

import pytest
from pathlib import Path


@pytest.fixture
def project_root():
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def data_dir(project_root):
    """Return the data directory."""
    return project_root / "data"


@pytest.fixture
def models_dir(project_root):
    """Return the models directory."""
    return project_root / "models"


@pytest.fixture
def processed_data_dir(data_dir):
    """Return the processed data directory."""
    return data_dir / "processed"
