# tests/conftest.py
"""
conftest.py — makes src/ importable so tests and the pipeline share one module
instance each (important: 01_fetch.py catches YuantaError, which must be the
same class the tests raise).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def load(filename: str):
    """Load a module whose file name starts with a digit (01_fetch.py)."""
    path = SRC / filename
    module_name = "pipeline_" + path.stem
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def yuanta():
    import yuanta_client

    return yuanta_client


@pytest.fixture(scope="session")
def quality():
    import data_quality

    return data_quality


@pytest.fixture(scope="session")
def fetch_mod():
    return load("01_fetch.py")


@pytest.fixture(scope="session")
def freshness():
    import check_freshness

    return check_freshness


@pytest.fixture(scope="session")
def repair():
    import repair_data

    return repair_data


@pytest.fixture(scope="session")
def telegram_check():
    import telegram_check

    return telegram_check


@pytest.fixture(scope="session")
def write_summary():
    import write_summary

    return write_summary


@pytest.fixture(scope="session")
def telegram():
    return load("04_telegram.py")
