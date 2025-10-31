"""Pytest configuration to ensure the local `nicegui` test stub is used.

If a real `nicegui` package is installed in the venv, imports like
`from nicegui import ui` may resolve to the installed package instead of
the repository-local `nicegui/__init__.py` stub we add for tests. To make
tests deterministic we load the local stub and insert it into sys.modules
under the name `nicegui` before test collection.
"""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path


def pytest_sessionstart(session):
    repo_root = Path(__file__).parent
    stub_path = repo_root / "nicegui" / "__init__.py"
    if not stub_path.exists():
        # nothing to do
        return

    try:
        spec = importlib.util.spec_from_file_location("nicegui", str(stub_path))
        module = importlib.util.module_from_spec(spec)
        # execute the module in its own namespace
        spec.loader.exec_module(module)  # type: ignore
        # inject into sys.modules so `import nicegui` resolves to this stub
        sys.modules["nicegui"] = module
    except Exception:
        # if loading fails, don't block test collection; let import fail later
        return
