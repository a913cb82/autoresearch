"""Shared test helper: put a fixture pi on PATH."""

import os
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

FIXTURES = Path(__file__).parent / "fixtures"


@contextmanager
def fixture_pi(variant: str):
    """Prepend fixtures/bin_<variant}/ (containing executable `pi`) to PATH."""
    bindir = str(FIXTURES / f"bin_{variant}")
    with mock.patch.dict(
        os.environ, {"PATH": bindir + os.pathsep + os.environ["PATH"]}
    ):
        yield
