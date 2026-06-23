# conftest.py - Shared pytest fixtures for the switchboard test suite.
#
# Only fixtures used by MORE THAN ONE split test file live here.
from switchboard import cli

import pytest


@pytest.fixture(autouse=True)
def reset_markdown():
    """Reset the module-level _MARKDOWN flag between every test."""
    cli._MARKDOWN = False
    yield
    cli._MARKDOWN = False
