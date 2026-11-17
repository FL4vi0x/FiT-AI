import pytest

from fit_ai.adapters.octave import load_sdk
from fit_ai.config import Settings


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def sdk():
    """The official OCTAVE SDK, loaded in place (only for its exception classes in unit tests)."""
    return load_sdk(Settings.from_env().octave_sdk_path)
